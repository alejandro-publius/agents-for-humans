# Upstream note for the Strands Agents SDK (1.55.1): the after-model retry loop, fail-open handlers, adjacent user turns, interrupts per tool use id

Found while red-teaming Last Elevator. Written so the owner can post it as
a GitHub issue on strands-agents (a small, sourced contribution back).

## Observation

`SteeringHandler.steer_after_model` returning `Guide` sets
`AfterModelCallEvent.retry = True`, and `event_loop._handle_model_execution`
loops `while True` on that flag inside one event-loop cycle
(`strands/event_loop/event_loop.py`, the block that checks
`after_model_call_event.retry` and `continue`s). Nothing counts the
retries. `limits={"turns": n}` is checked at the top of each cycle, so it
never fires while the model keeps producing a response the handler
rejects. A model that never complies is re-called until something else
stops it: the model raising, a token budget on the provider, or an
external cap.

## Minimal reproduction (offline, no provider)

```python
from strands import Agent
from strands.models.model import Model
from strands.vended_plugins.steering.core.action import Guide, Proceed
from strands.vended_plugins.steering.core.handler import SteeringHandler

class Talker(Model):
    calls = 0
    def update_config(self, **kw): ...
    def get_config(self): return {}
    async def structured_output(self, *a, **kw): raise NotImplementedError
    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        type(self).calls += 1
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": "no"}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, "metrics": {"latencyMs": 1}}}

class AlwaysGuide(SteeringHandler):
    async def steer_after_model(self, *, agent, message, stop_reason, **kw):
        if Talker.calls >= 50:  # the only thing that ends the loop here is the handler giving up
            return Proceed(reason="giving up after 50 retries")
        return Guide(reason="try again")

result = Agent(model=Talker(), plugins=[AlwaysGuide()], callback_handler=None)("hi", limits={"turns": 2})
print("stop reason:", result.stop_reason, "model calls:", Talker.calls)
```

Expected: the run ends after the turn limit or after a bounded number
of retries. Observed: `stop reason: end_turn model calls: 50`; the
retries continue until the handler itself gives up. Change the 50 to
2000 and the model is called 2000 times. Timings in the dispatch sandbox
with this instant model: 200 retries in 0.3 s, 1000 in 7 s, 2000 in 27
s, so the per-retry cost also grows with the count even though the
default sliding-window conversation manager holds the message list at
40 (cause not chased). The test
`test_upstream_note_reproduction_runs_as_written` executes this snippet
as written, so a Strands release that bounds the loop flips it first.

## A second observation: a handler that raises fails open

In the same file, `steer_after_model` is wrapped in `except Exception`,
which logs at debug level and returns, so the model's response is
accepted as if the handler had returned `Proceed`. (The before-tool path
does the same.) A gate meant to fail closed has to catch its own
exceptions and return `Guide`; Last Elevator's handlers do
(`test_gates_fail_closed_on_internal_error`). A note in the docs, or a
`fail_closed` option on `SteeringHandler`, would save the next builder the
surprise.

## A third observation: two Guides in a row leave two adjacent user turns

Each `Guide` after the model discards the assistant response and appends
the reason as a user turn. Two rejections in a row therefore leave two
adjacent user text turns in `agent.messages`. `BedrockModel` separates a
tool-result turn from a following user turn at request time (the fix for
#1223) but not two text turns, and Bedrock's Converse API requires the
roles to alternate (its `ValidationException` says "A conversation must
alternate between user and assistant roles"). We have not yet observed
the rejection on a live call (the laptop's first live run will), but the
adjacency itself is reproducible offline: after two Guides, the wrapped
model receives `user, assistant, user(toolResult), user, user`. Last
Elevator folds adjacent user text turns into one turn, request-locally,
in the same wrapper that counts calls (`sendable_turns` in
`le_dispatch/budget.py`; test
`test_after_two_guides_the_model_never_sees_two_adjacent_user_turns`).
The persisted conversation is untouched. A request-local fold in
`BedrockModel._format_bedrock_messages`, next to the existing separator,
would cover every steering user.

Measured through the real adapter with a stand-in client that enforces
the alternation rule (`make wire`, `docs/evidence/bedrock-wire.md`): with
the fold alone, the existing separator still costs one rejected request
per process and model id, because it is applied only after a
`ValidationException`; applying it ahead of time, as the same wrapper
now does, brings the rejected count to zero and changes nothing on a
model that would have accepted the request. An eager separator in
`_format_bedrock_messages` would do the same for everyone.

## A fourth, for the steering docs: an Interrupt is per tool use id

`BeforeToolCallEvent.interrupt()` keys the interrupt on the tool use id
(`v1:before_tool_call:<toolUseId>:<uuid5(name)>`), which is right: the
response belongs to that call. What the steering docs do not say is what
follows for a `steer_before_tool` that returns `Interrupt`: on the
resumed pass the handler is called again for the interrupted call and
must return the same `Interrupt` to receive the answer, but if another
plugin then cancels that call (a `Guide`) and the model retries, the
retry has a new tool use id, and a handler that returns `Interrupt`
again raises a new interrupt. In Last Elevator that meant the rider
would have been asked twice. The handler now returns `Interrupt` only
for the tool use ids the pending interrupts carry and decides later
calls in the same pass on the stored answer
(`DecisionInterruptHandler.is_interrupted_call`, test
`test_a_resumed_call_the_gates_retry_does_not_ask_the_rider_again`). A
sentence in the steering docs, or a helper on the event that says
whether a response is already stored for this call, would save the
next user the same afternoon.

## A fifth, for the Bedrock adapter: two retry layers stack by default

`BedrockModel` builds its boto3 client with a `BotocoreConfig` that sets
`user_agent_extra` and `read_timeout` and leaves `retries` alone, so the
client runs botocore's default "legacy" retry mode: a `ThrottlingException`
is sent again up to five times with a random backoff of up to 1, 2, 4 and
8 seconds before the adapter raises `ModelThrottledException`. The SDK's
own `ModelRetryStrategy` (six attempts, waits of 4, 8, 16, 32 and 64
seconds) then retries the whole thing. Stacked, one throttled model call
is thirty requests and about two and a half minutes, and neither the
trace nor anything counting model calls sees the twenty-four requests the
client made on its own. The reproduction is a real client whose HTTP send
is replaced by a 429 through botocore's `before-send` hook: five requests
under the default configuration, one under
`Config(retries={"total_max_attempts": 1, "mode": "standard"})`
(`test_botocores_own_retry_layer_is_off_on_the_live_client`; note that
`max_attempts: 1` still means two requests, botocore counts it as retries).
Last Elevator builds every live client on that configuration and bounds
the SDK's strategy to four attempts (`le_dispatch/live.py`), so a throttle
costs at most four requests and fourteen seconds and every retry is one
the trace shows. A default of `total_max_attempts: 1` in the adapter's
`BotocoreConfig`, or a sentence in the Bedrock provider docs that the two
layers stack, would give every user one priced layer instead of two.

## Suggested fixes

1. A cap on hook-requested model retries per cycle (a `Limits` field such
   as `model_retries`, or a default of a small number with a clear stop
   reason like `limit_model_retries`), and a note in the steering docs that
   `Guide` after the model is a retry request the caller should bound.
2. A `fail_closed` option on `SteeringHandler` (or a documented note) for
   the exception path.
3. A request-local fold of adjacent user text turns in
   `BedrockModel._format_bedrock_messages`, next to the existing
   tool-result separator, and that separator applied ahead of the first
   rejection rather than after it.
4. In the steering docs: an `Interrupt` from `steer_before_tool` is per
   tool use id; a handler that must not ask twice keeps the ids of the
   interrupts it is answering (or the event exposes whether a response
   is stored for this call).
5. `retries={"total_max_attempts": 1, "mode": "standard"}` in the
   `BotocoreConfig` the Bedrock adapter builds by default (its own
   `ModelRetryStrategy` is the retry layer), or a note in the provider
   docs that botocore's layer runs underneath it.

## What Last Elevator does meanwhile

Every agent built by `build_agent` wraps the model in a per-run call cap
(`le_dispatch/budget.py`); the cap trip is the expected control path and
the delivery layer composes the plan in code (`deliver()`), so the rider
always gets a plan. Test: `test_delivery_falls_back_to_code_when_the_model_never_complies`.
The same wrapper makes every request sendable (above) and exposes the
wrapped model's `config` so the trace keeps the model id.
