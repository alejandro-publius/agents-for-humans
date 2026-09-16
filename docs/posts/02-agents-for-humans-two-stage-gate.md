# Agents for Humans: a two-stage steering gate in Strands, before the tool and after the model

Last Elevator's promise to a BART rider is small and strict: the plan
that reaches you names a real station, carries BART's own option in
BART's order, and states minutes the policy engine computed. The model
never gets to decide any of those. This post shows how the Strands Agents
SDK enforces that, and what changed when we added a second gate.

## Stage 0: the knowledge-base hook

A `HookProvider` registers a callback on `BeforeToolCallEvent`. If the
tool call names a station or elevator that is not in the frozen knowledge
base, the callback sets `event.cancel_tool` to a reason. The tool never
runs; the reason lands in the tool result with error status, so the model
sees exactly why.

```python
class KBHook(HookProvider):
    def register_hooks(self, registry, **kw):
        registry.add_callback(BeforeToolCallEvent, self.check)

    def check(self, event):
        args = event.tool_use["input"]
        if "station" in args and not kb.has_station(args["station"]):
            event.cancel_tool = f"Cancelled: {args['station']!r} is not a station in the knowledge base"
```

## Stage 1: steering before the tool

A `SteeringHandler` implements `steer_before_tool`. The draft must carry
the policy engine's top feasible option, in BART's published order. If it
does not, the handler returns `Guide(reason=...)`: Strands cancels the
call, feeds the reason back, and the model retries.

## Stage 2: steering after the model

A model can still write the wrong option, or invented minutes, into the
final structured plan. So the same handler implements `steer_after_model`.
When the assistant message carries the structured-output tool call
(Strands names it after the Pydantic class, here `Plan`), code checks the
plan's station and elevator against the KB, the option against the policy
engine's top option, and `added_minutes` against its minutes. On mismatch
it returns `Guide`: Strands discards the response, appends the reason as
a user turn, and calls the model again. On match, `Proceed`.

```python
async def steer_after_model(self, *, agent, message, stop_reason, **kw):
    plan = extract_plan(message, "Plan")
    if plan is None:
        return Proceed(reason="no final plan in this message")
    problems = self.check_plan(plan)
    if problems:
        return Guide(reason="Plan rejected: " + "; ".join(problems))
    return Proceed(reason="plan matches the policy engine and the knowledge base")
```

Four details matter. `steer_after_model` accepts only `Proceed` or
`Guide`; the model has already responded. The gates fail closed: an
exception inside a gate returns `Guide`, never `Proceed`. The rider
message is never a sentence the model wrote alone: code composes a few
sentences from the policy decision and BART's own option text, and the
gate accepts the message only if it is one of them verbatim, so a hostile
sentence injected through the feed is discarded even when it carries no
number and no code. And the retry loop is bounded: in Strands 1.55.1 a
Guide after the model re-calls the model inside the same turn without
limit, so every run carries a cap on model calls, and at the cap code
composes the plan; the rider is never left without one.

## Proving it without a model

A scripted `Model` replays a fixed sequence: an unknown elevator, the
wrong option, a correct call, a wrong final plan, a correct one. The test
asserts exactly one hook cancellation, one Guide before the tool, one
Guide after the model, one Proceed, and a plan with the policy engine's
values. No network: the fixtures make every socket call raise.

A scripted adversary then attacks 140 times: fake stations, wrong
options, invented minutes, the same tricks hidden in the rider's
sentence, hostile sentences injected as if through the outage feed, and
runs where the model never complies at all. Hostile stations, options,
minutes and unapproved sentences that reached the rider: 0, 0, 0, 0;
every run still delivered a plan. Then exhaustively: every one of the 194
frozen cases times every attack, 2716 runs, the same zeros (fixture run;
the rerun on the real knowledge base and policy engine is pending).
Turning the steering handler off makes the same counters climb, which is
how we know the counters see leaks.

Then we removed the gates one at a time and ran the same 140 attacks
again, because zero leaks with every gate in place is necessary, not
sufficient. Take out the gate after the model and 120 of 140 runs leak.
Take out only the approved-sentence check and every injected sentence
reaches the rider. Take out both gates before the tool and nothing leaks:
they are the in-process twin of the gateway's Cedar policy and the reason
a hostile tool call never runs, not the rider's last line.

## What the SDK taught us

Five findings, each with an offline reproduction that runs as a test, are
written up for the maintainers in the repo's upstream note. The two that
shape every agent we build: a `Guide` after the model retries inside one
turn with no counter, so the per-run cap on model calls is the only limit
that fires on a model that never complies; and a steering handler that
raises is treated as `Proceed`, so a gate that must fail closed catches
its own errors and returns `Guide`.

Strands' own steering benchmark reports prompt-only agents at 82.5
percent, hard-coded workflows at 80.8 percent, and agents with steering
handlers recovering from every mistake; our enforced versus no-steering
eval reproduces that benchmark's shape on a real transit policy (live
rows pending).

Repo: TODO. Video: TODO.
