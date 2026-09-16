"""The live path through Strands' real Bedrock adapter, offline.

Between the agent and the network everything is the SDK's own code: `strands.models.BedrockModel`
formats the Converse request (the system prompt, the two tool specs, the conversation), parses the
stream and raises the SDK's exceptions; the event loop retries what it retries. Only the boto3 client
is replaced. `FakeBedrockRuntime` records every `converse_stream` request, enforces the Converse rules a
retry can violate (roles alternate, every toolUse is answered, tool blocks need a toolConfig) with the
ValidationException Bedrock sends, and replies with scripted stream chunks (the same steps the scripted
model uses) or raises a scripted ClientError. The real client underneath is pointed at a closed local
port before it is swapped out; no path leads to AWS.

What runs here that the scripted model never exercised: the request Bedrock will receive (written to
docs/evidence/bedrock-request.json), whether every retry is sendable (the folding in budget.py and the
SDK's own tool-result separator, measured: one rejected request per process per model id), what a
permission error, a throttle or a truncated response costs (one call, and the rider still gets the
plan; the SDK's backoff, then the plan), and the forced structured-output request. `make wire` writes
the evidence and results/bedrock_wire.json.

Two stand-ins play a model instead of replaying a script. `LearnerRuntime` reads the conversation (the
station and elevator from the prompt, the option and an approved sentence from the tool result or the
gates' feedback), one belief per case, so one client serves a whole live-eval entry (`--stand-in` on
the live scripts) and the human moment (asked once, then sent or held). `PersonaRuntime` plays one
convergence persona, a belief wrong from the start, so `make wire-convergence` measures whether the
gates' feedback is readable in each adapter format (JSON tool results with a status flag for Anthropic
model ids, text without one for Nova). Both are plumbing proof; neither is a claim about a live model.
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import re
import types
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from . import budget, live, tracing
from .gates import AgentBundle, DeliveryOutcome, build_agent, deliver
from .interfaces import KBSet, PolicyCallable, Trip, claimable, data_source
from .messages import composed_plan
from .scripted_model import plan_call, text_turn, tool_call

# the message the SDK's own separator looks for (strands.models.bedrock._TOOL_RESULT_TURN_VALIDATION_MESSAGE)
TOOL_RESULT_TURN_MESSAGE = "Conversation blocks and tool result blocks cannot be provided in the same turn."
ALTERNATION_MESSAGE = "(stand-in) roles must alternate between user and assistant"
UNANSWERED_MESSAGE = "(stand-in) every toolUse must be answered by a toolResult in the next user turn"
TOOL_CONFIG_MESSAGE = "(stand-in) toolConfig is required when messages contain tool blocks"
DEAD_ENDPOINT = "http://127.0.0.1:9"  # the discard port: a request that reached the real client would fail here
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def client_error(code: str, message: str, operation: str = "ConverseStream") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


def converse_rule_violation(request: dict[str, Any]) -> str | None:
    """The first Converse rule the request breaks, as the message Bedrock would send, or None."""
    messages = request.get("messages", [])
    has_tool_blocks = False
    for i, message in enumerate(messages):
        content = message.get("content", [])
        has_tool_blocks = has_tool_blocks or any("toolUse" in b or "toolResult" in b for b in content)
        if i == 0 and message.get("role") != "user":
            return ALTERNATION_MESSAGE
        if i and messages[i - 1].get("role") == message.get("role"):
            previous = messages[i - 1].get("content", [])
            if message.get("role") == "user" and previous and all("toolResult" in b for b in previous):
                return TOOL_RESULT_TURN_MESSAGE
            return ALTERNATION_MESSAGE
        if message.get("role") == "assistant":
            asked = {b["toolUse"]["toolUseId"] for b in content if "toolUse" in b}
            if asked:
                following = messages[i + 1].get("content", []) if i + 1 < len(messages) else []
                answered = {b["toolResult"]["toolUseId"] for b in following if "toolResult" in b}
                if asked - answered:
                    return UNANSWERED_MESSAGE
    if has_tool_blocks and "toolConfig" not in request:
        return TOOL_CONFIG_MESSAGE
    return None


@dataclass
class Exchange:
    """One request to the stand-in and what came back."""

    request_no: int
    roles: list[str]
    accepted: bool
    reply: str  # "tool_use draft_plan", "tool_use Plan", "text", or the error code
    detail: str = ""


class FakeBedrockRuntime:
    """Stands in for boto3's bedrock-runtime client. Records requests, enforces the Converse rules, replays
    scripted steps (a list of stream chunks, or a ClientError to raise)."""

    def __init__(self, steps: list[Any], region: str = "us-west-2"):
        self.steps = list(steps)
        self.region = region
        self.requests: list[dict[str, Any]] = []
        self.exchanges: list[Exchange] = []
        self.rejected = 0
        self.consumed = 0
        self.meta = types.SimpleNamespace(region_name=region)

    def converse(self, **request: Any) -> Any:  # pragma: no cover - the adapter streams by default
        raise AssertionError("the package configures the streaming path; converse() is not expected")

    def converse_stream(self, **request: Any) -> dict[str, Any]:
        roles = self._admit(request)
        step = self._reply(request)
        if isinstance(step, Exception):
            code = step.response["Error"]["Code"] if isinstance(step, ClientError) else type(step).__name__
            self.exchanges.append(Exchange(len(self.requests), roles, True, code, str(step)[:120]))
            raise step
        self.exchanges.append(Exchange(len(self.requests), roles, True, describe_step(step)))
        return {"stream": iter(copy.deepcopy(step))}

    def _admit(self, request: dict[str, Any]) -> list[str]:
        """Record the request; reject it the way Bedrock would if it breaks a Converse rule."""
        self.requests.append(copy.deepcopy(request))
        roles = [m.get("role", "?") for m in request.get("messages", [])]
        violation = converse_rule_violation(request)
        if violation:
            self.rejected += 1
            self.exchanges.append(Exchange(len(self.requests), roles, False, "ValidationException", violation))
            raise client_error("ValidationException", violation)
        return roles

    def _reply(self, request: dict[str, Any]) -> Any:
        """The next scripted step (stream chunks, or an exception to raise); subclasses play a model instead."""
        idx = self.consumed
        self.consumed += 1
        return self.steps[idx] if idx < len(self.steps) else text_turn("[script exhausted]")


class LearnerRuntime(FakeBedrockRuntime):
    """A stand-in that plays a model which reads the conversation: the station and elevator from the prompt,
    the option and the sentence from what the tool result and the gates say. One belief per case (a fresh
    conversation resets it), so one client serves a whole live-eval entry. The same Converse rules apply.
    Plumbing proof for the live scripts (`--stand-in`); never a claim about a model."""

    instances = 0  # tool use ids carry the instance number: a resumed conversation sees ids from two learners

    def __init__(self, region: str = "us-west-2", first_guess: str = "transit"):
        super().__init__([], region)
        self.first_guess = first_guess
        self.learner: Any = None
        self.cases = 0
        LearnerRuntime.instances += 1
        self.instance = LearnerRuntime.instances

    def _reply(self, request: dict[str, Any]) -> Any:
        from .adaptive import AdaptiveModel, Belief

        messages = request.get("messages", [])
        tools = [t.get("toolSpec", {}).get("name") for t in request.get("toolConfig", {}).get("tools", [])]
        if tools == ["RiderNote"]:  # the note reader's forced structured output: read the note by its words
            self.consumed += 1
            return note_call(_first_text(messages), f"l{self.instance}n{self.consumed}")
        if len(messages) == 1 or self.learner is None:  # a fresh conversation: a new case
            prompt = _first_text(messages)
            elevator = _PROMPT_ELEVATOR.search(prompt)
            station = _PROMPT_STATION.search(prompt)
            self.learner = AdaptiveModel(
                Belief(
                    station=station.group(1) if station else (elevator.group(1).split("-")[0] if elevator else "?"),
                    elevator=elevator.group(1) if elevator else "?",
                    option=self.first_guess,
                    minutes=None,
                    message="",
                    reads_tool_result=True,
                    id_prefix=f"l{self.instance}c{self.cases + 1}-",
                )
            )
            self.cases += 1
        self.consumed += 1
        return self.learner.next_step(_as_model_messages(messages))


NOTE_WORDS = {  # what the stand-in reads a note by: the first phrase found is the quote (so the check keeps it)
    "avoid_ramps": ("no ramps", "no ramp", "ramp"),
    "avoid_stairs": ("no stairs", "stairs"),
    "avoid_transit": ("no bus", "no transit", "no streetcar", "bus"),
    "avoid_backtracking": ("no backtracking", "backtrack"),
    "avoid_shuttle": ("no shuttle", "shuttle"),
}


def note_call(prompt: str, tool_use_id: str) -> list[dict[str, Any]]:
    """A RiderNote structured-output call read from the note in the prompt, the way a plain model would: a
    kind per phrase found, the phrase as the quote. An injection in the note finds no phrase and rules
    nothing out."""
    text = prompt.split("<note>")[-1].split("</note>")[0].lower() if "<note>" in prompt else prompt.lower()
    constraints = []
    for kind, phrases in NOTE_WORDS.items():
        found = next((p for p in phrases if p in text), None)
        if found:
            constraints.append({"kind": kind, "quote": found})
    return plan_call({"constraints": constraints}, tool_use_id, model_name="RiderNote")


class PersonaRuntime(FakeBedrockRuntime):
    """A stand-in that plays one convergence persona (a belief wrong from the start) through the real adapter:
    the same AdaptiveModel the offline study uses, reading the conversation as the adapter formats it for the
    model id (JSON tool results with a status flag for Anthropic, text without one for Nova)."""

    def __init__(self, model: Any, region: str = "us-west-2"):
        super().__init__([], region)
        self.model = model

    def _reply(self, request: dict[str, Any]) -> Any:
        self.consumed += 1
        return self.model.next_step(_as_model_messages(request.get("messages", [])))


def wired_persona_model(adaptive: Any, model_id: str = DEFAULT_MODEL_ID, region: str = "us-west-2") -> Any:
    model = live.model(model_id, region, endpoint_url=DEAD_ENDPOINT)
    model.client = PersonaRuntime(adaptive, region)
    return model


def run_wire_convergence(
    kb: KBSet,
    policy: PolicyCallable,
    cases: list[Any],
    model_ids: tuple[str, ...],
    *,
    personas: tuple[str, ...] | None = None,
    cap: int = 12,
) -> dict[str, Any]:
    """The convergence study through the real adapter: every persona times every case, per model id (the
    adapter formats tool results differently per model family). Converged means the plan reached the rider
    with the policy engine's values, composed by the model, within the cap; no request rejected."""
    from .adaptive import PERSONAS, AdaptiveModel, persona_belief
    from .plan import Plan

    personas = personas or PERSONAS
    per_model: dict[str, Any] = {}
    total = converged = rejected = 0
    worst = 0
    for model_id in model_ids:
        runs = ok_runs = 0
        calls_max = 0
        failed: list[str] = []
        by_persona: dict[str, dict[str, int]] = {}
        for persona in personas:
            p_ok = p_runs = 0
            for i, case in enumerate(cases):
                dest = "EMBR" if case.station != "EMBR" else "MONT"
                trip = Trip(f"wire-{i:03d}", case.station, dest, (case.elevator,))
                d = policy(trip)
                belief = persona_belief(persona, d)
                belief.id_prefix = f"{persona[:3]}{i}-"
                model = wired_persona_model(AdaptiveModel(belief, name=f"wire-{persona}"), model_id)
                bundle = build_agent(model, kb, policy, trip, max_model_calls=cap)
                with quiet_sdk_logs():
                    out = deliver(bundle)
                plan = out.plan or {}
                good = (
                    out.composed_by == "model"
                    and plan.get("option") == d.top_option
                    and plan.get("added_minutes") == d.minutes_for(d.top_option)
                    and plan.get("station") == d.station
                    and plan.get("elevator") == d.elevator
                    and Plan(**plan).status == "send"
                )
                runs += 1
                p_runs += 1
                rejected += model.client.rejected
                calls_max = max(calls_max, getattr(bundle.agent.model, "calls", 0) or 0)  # the cap wrapper counts
                if good:
                    ok_runs += 1
                    p_ok += 1
                else:
                    failed.append(f"{persona}/{case.case_id}: {out.composed_by} {out.stop_reason} {out.reason[:80]}")
            by_persona[persona] = {"runs": p_runs, "converged": p_ok}
        per_model[model_id] = {
            "runs": runs,
            "converged": ok_runs,
            "max_calls": calls_max,
            "by_persona": by_persona,
            "failed": failed[:20],
        }
        total += runs
        converged += ok_runs
        worst = max(worst, calls_max)
    return {
        "provenance": {
            "run": "every convergence persona times every case in the slice, through Strands' real BedrockModel "
            "with a stand-in client per model id; nothing was sent",
            "claimable": claimable(),
            "source": data_source(),
            "note": "Plumbing proof about the gates' feedback as a model reads it in each adapter format; never "
            "a claim about a live model.",
        },
        "model_ids": list(model_ids),
        "cases": len(cases),
        "personas": list(personas),
        "runs": total,
        "converged": converged,
        "max_calls": worst,
        "rejected_by_converse_rules": rejected,
        "per_model": per_model,
    }


_PROMPT_ELEVATOR = re.compile(r"\b([A-Z0-9]{4}-E\d+)\b")
_PROMPT_STATION = re.compile(r"\bat ([A-Z0-9]{4})\b")


def _first_text(messages: list[dict[str, Any]]) -> str:
    for m in messages:
        for b in m.get("content", []):
            if isinstance(b, dict) and "text" in b:
                return b["text"]
    return ""


def _as_model_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The request as a model reads it: a JSON tool-result block (what the adapter sends Anthropic models) as
    its text (what it sends Nova); the adaptive stand-in parses the text either way."""
    out = []
    for m in messages:
        blocks = []
        for b in m.get("content", []):
            if isinstance(b, dict) and "toolResult" in b:
                tr = dict(b["toolResult"])
                tr["content"] = [
                    {"text": json.dumps(c["json"])} if isinstance(c, dict) and "json" in c else c
                    for c in tr.get("content", [])
                ]
                blocks.append({"toolResult": tr})
            else:
                blocks.append(b)
        out.append({**m, "content": blocks})
    return out


def wired_learner_model(model_id: str = DEFAULT_MODEL_ID, region: str = "us-west-2") -> Any:
    """A real BedrockModel whose client is the learner stand-in (one client serves every case)."""
    model = live.model(model_id, region, endpoint_url=DEAD_ENDPOINT)
    model.client = LearnerRuntime(region)
    return model


def describe_step(step: list[dict[str, Any]]) -> str:
    for chunk in step:
        start = chunk.get("contentBlockStart", {}).get("start", {})
        if "toolUse" in start:
            return f"tool_use {start['toolUse']['name']}"
    return "text"


def wired_model(steps: list[Any], model_id: str = DEFAULT_MODEL_ID, region: str = "us-west-2") -> Any:
    """A real BedrockModel whose client is the stand-in. The real client is built first on the live
    configuration (no credentials are needed to build one), pointed at the dead endpoint, then replaced."""
    model = live.model(model_id, region, endpoint_url=DEAD_ENDPOINT)
    model.client = FakeBedrockRuntime(steps, region)
    return model


SENDABILITY = ("both", "fold_only", "none")


@contextlib.contextmanager
def sendability(mode: str) -> Iterator[None]:
    """The measurement switch for the cap wrapper's request-local passes: both (the package), fold_only (the
    SDK's lazy separator is left to handle the tool-result pair), none (the conversation as the SDK leaves
    it, adjacent user turns and all)."""
    if mode not in SENDABILITY:
        raise ValueError(f"sendability must be one of {SENDABILITY}, not {mode!r}")
    original = budget.sendable_turns
    if mode == "fold_only":
        budget.sendable_turns = budget.merge_adjacent_user_turns  # type: ignore[assignment]
    elif mode == "none":
        budget.sendable_turns = lambda messages: messages  # type: ignore[assignment]
    try:
        yield
    finally:
        budget.sendable_turns = original  # type: ignore[assignment]


@dataclass
class WireRun:
    name: str
    outcome: DeliveryOutcome
    bundle: AgentBundle
    fake: FakeBedrockRuntime
    mode: str = "both"

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.fake.requests

    interrupts_raised: int | None = None  # the human-moment runs only

    def summary(self) -> dict[str, Any]:
        gate = self.bundle.gate
        out = {
            "composed_by": self.outcome.composed_by,
            "stop_reason": self.outcome.stop_reason,
            "model_calls": getattr(self.bundle.agent.model, "calls", 0),  # the cap wrapper counts
            "requests": len(self.fake.requests),
            "rejected_by_converse_rules": self.fake.rejected,
            "hook_cancels": self.bundle.hook.cancels,
            "guide_before_tool": gate.count(tracing.GUIDE_BEFORE) if gate else 0,
            "guide_after_model": gate.count(tracing.GUIDE_AFTER) if gate else 0,
            "sendability": self.mode,
            "reason": self.outcome.reason,
        }
        if self.interrupts_raised is not None:
            out["interrupts_raised"] = self.interrupts_raised
        return out


def run_human_moment(
    name: str, kb: KBSet, policy: PolicyCallable, trip: Trip, answer: bool, *, model_id: str = DEFAULT_MODEL_ID
) -> WireRun:
    """After dark, with the learner stand-in (its first call is wrong): the run pauses on the interrupt, the
    rider answers once, the resumed pass is retried by the gates and ends sent or held; through the real
    adapter, so the resumed request is one Bedrock accepts."""
    import tempfile

    from .interrupts import DecisionMemory, Inbox, build_decision_run

    model = wired_learner_model(model_id)
    tmp = Path(tempfile.mkdtemp(prefix="le-wire-human-"))
    run = build_decision_run(model, kb, policy, trip, inbox=Inbox(tmp / "inbox.json"), memory=DecisionMemory())
    with quiet_sdk_logs():
        first = run.start()
        out = run.resume(answer) if first.state == "pending" else first
    reason = "" if first.state == "pending" else f"the run did not pause: {first.state}"
    outcome = DeliveryOutcome(
        out.plan.model_dump() if out.plan else None,
        out.composed_by,
        out.state,
        getattr(model, "calls", None),
        reason,
    )
    return WireRun(name, outcome, run.bundle, model.client, "both", run.handler.count(tracing.INTERRUPT_RAISED))


def run_wire(
    name: str,
    steps: list[Any],
    kb: KBSet,
    policy: PolicyCallable,
    trip: Trip,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    mode: str = "both",
    retry_strategy: Any = None,
) -> WireRun:
    model = wired_model(steps, model_id)
    bundle = build_agent(model, kb, policy, trip, retry_strategy=retry_strategy)
    with sendability(mode), quiet_sdk_logs():
        outcome = deliver(bundle)
    return WireRun(name, outcome, bundle, model.client, mode)


@contextlib.contextmanager
def quiet_sdk_logs() -> Iterator[None]:
    """The SDK warns about the scripted failures (a truncated tool input, a throttle); they are the point of
    the run, and the outcome records them, so keep the output to the table."""
    logger = logging.getLogger("strands")
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)


def quick_retries() -> Any:
    """The live throttle strategy's attempts without its waits, for an offline run (the live path waits
    2 s, 4 s, 8 s between its four attempts, then the exception, which the delivery layer turns into a
    code-composed plan; le_dispatch/live.py)."""
    from strands.event_loop._retry import ModelRetryStrategy

    return ModelRetryStrategy(max_attempts=live.ATTEMPTS, initial_delay=0, max_delay=0)


# the scripts: what a live model could do, replayed through the real adapter


def compliant_steps(decision: Any) -> list[Any]:
    d = decision
    return [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        plan_call(composed_plan(d), "p1"),
    ]


def retries_steps(decision: Any, kb: KBSet) -> list[Any]:
    """Every gate once, then twice after the model: a station outside the knowledge base (the hook cancels),
    a wrong option (the option gate guides before the tool), the right draft, two Plans with the wrong
    option (two Guides after the model, in a row), then the right Plan."""
    d = decision
    foreign = "ZZZZ"
    assert foreign not in kb.stations
    wrong = next(o.label for o in d.ranked if o.label != d.top_option) if len(d.ranked) > 1 else d.top_option
    good = {"station": d.station, "elevator": d.elevator, "option": d.top_option}
    bad_plan = {**composed_plan(d), "option": wrong, "added_minutes": d.minutes_for(wrong)}
    return [
        tool_call("draft_plan", {**good, "station": foreign}, "t1"),
        tool_call("draft_plan", {**good, "option": wrong}, "t2"),
        tool_call("draft_plan", good, "t3"),
        plan_call(bad_plan, "p1"),
        plan_call(bad_plan, "p2"),
        plan_call(composed_plan(d), "p3"),
    ]


def access_denied_steps() -> list[Any]:
    return [
        client_error(
            "AccessDeniedException",
            "You don't have access to the model with the specified model ID.",
        )
    ]


def throttled_steps(decision: Any) -> list[Any]:
    return [client_error("ThrottlingException", "Too many requests, please wait before trying again.")] + (
        compliant_steps(decision)
    )


def prose_then_forced_steps(decision: Any) -> list[Any]:
    """The model answers in prose after the draft; the SDK forces the structured output (a user instruction
    and toolChoice any), and the model returns the Plan."""
    d = decision
    return [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        text_turn("Here is your plan: take the alternate elevator, about four minutes more."),
        plan_call(composed_plan(d), "p1"),
    ]


def hung_steps() -> list[Any]:
    """The stream stays silent past the read timeout: botocore raises ReadTimeoutError (not a throttle, so the
    retry strategy does not retry it), the adapter lets it through, and the delivery layer composes the plan.
    Sixty seconds on the live client (le_dispatch/live.py); instant here."""
    from botocore.exceptions import ReadTimeoutError

    return [ReadTimeoutError(endpoint_url="https://bedrock-runtime.us-west-2.amazonaws.com/")]


def truncated_steps(decision: Any) -> list[Any]:
    """The model runs out of output tokens halfway through the tool call's JSON (stopReason max_tokens); the
    SDK raises MaxTokensReachedException and the delivery layer composes the plan."""
    d = decision
    partial = '{"station": "' + d.station + '", "elev'
    truncated = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": "draft_plan"}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": partial}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "max_tokens"}},
        {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, "metrics": {"latencyMs": 1}}},
    ]
    return [truncated] + compliant_steps(d)


SCENARIOS = (
    "compliant",
    "retries",
    "retries_fold_only",
    "retries_no_passes",
    "access_denied",
    "throttled",
    "truncated",
    "hung",
    "prose_then_forced",
    "human_moment_yes",
    "human_moment_no",
)


def run_all(kb: KBSet, policy: PolicyCallable, trip: Trip, model_id: str = DEFAULT_MODEL_ID) -> dict[str, WireRun]:
    d = policy(trip)
    retries = retries_steps(d, kb)
    return {
        "compliant": run_wire("compliant", compliant_steps(d), kb, policy, trip, model_id=model_id),
        "retries": run_wire("retries", retries, kb, policy, trip, model_id=model_id),
        "retries_fold_only": run_wire(
            "retries_fold_only", retries, kb, policy, trip, model_id=model_id, mode="fold_only"
        ),
        "retries_no_passes": run_wire("retries_no_passes", retries, kb, policy, trip, model_id=model_id, mode="none"),
        "access_denied": run_wire("access_denied", access_denied_steps(), kb, policy, trip, model_id=model_id),
        "throttled": run_wire(
            "throttled", throttled_steps(d), kb, policy, trip, model_id=model_id, retry_strategy=quick_retries()
        ),
        "truncated": run_wire("truncated", truncated_steps(d), kb, policy, trip, model_id=model_id),
        "hung": run_wire("hung", hung_steps(), kb, policy, trip, model_id=model_id, retry_strategy=quick_retries()),
        "prose_then_forced": run_wire(
            "prose_then_forced", prose_then_forced_steps(d), kb, policy, trip, model_id=model_id
        ),
        "human_moment_yes": run_human_moment(
            "human_moment_yes", kb, policy, replace(trip, after_dark=True), True, model_id=model_id
        ),
        "human_moment_no": run_human_moment(
            "human_moment_no", kb, policy, replace(trip, after_dark=True), False, model_id=model_id
        ),
    }


def results_doc(runs: dict[str, WireRun], model_id: str) -> dict[str, Any]:
    return {
        "provenance": {
            "run": "the agent through Strands' real BedrockModel with a stand-in client that enforces the Converse "
            "rules; nothing was sent",
            "model_id": model_id,
            "claimable": claimable(),
            "source": data_source(),
            "note": "The stand-in replies with scripted chunks; the live run replaces it with Bedrock. Counts here "
            "measure the request path (what is sent, whether every retry is sendable, what an error costs), "
            "not model behaviour.",
        },
        "scenarios": {name: run.summary() for name, run in runs.items()},
    }


def first_request(runs: dict[str, WireRun]) -> dict[str, Any]:
    return runs["compliant"].requests[0]


def render_markdown(runs: dict[str, WireRun], model_id: str) -> str:
    lines = [
        "# The live path, offline: the agent through Strands' real Bedrock adapter",
        "",
        "Everything between the agent and the network is the SDK's own code (`strands.models.BedrockModel`",
        "formats the Converse request, parses the stream and raises its exceptions; the event loop retries what",
        "it retries). Only the boto3 client is a stand-in that records every request, enforces the Converse",
        "rules a retry can break (roles alternate; every toolUse answered; tool blocks need a toolConfig) with",
        "Bedrock's ValidationException, and replays scripted chunks. The real client was pointed at a closed",
        f"local port before it was replaced; nothing was sent. Model id on the request: `{model_id}`.",
        "",
        "The first request of the compliant run is in `bedrock-request.json` next to this file: the system",
        "prompt, the two tool specs (`draft_plan` and the structured-output tool `Plan`), the rider's prompt.",
        "",
    ]
    titles = {
        "compliant": "Compliant model: two calls, the plan is the model's",
        "retries": "Every gate, then two Guides in a row: every retry accepted at the first attempt",
        "retries_fold_only": "The same run with only the folding pass: the SDK's lazy separator costs one request",
        "retries_no_passes": "The same run with no pass: the second Guide is unsendable, code composes the plan",
        "access_denied": "A permission error on the model: one call, the rider still gets the plan",
        "throttled": "A throttle: the SDK retries, then the plan",
        "truncated": "A response cut off by the output token limit: one call, the rider still gets the plan",
        "hung": "A stream silent past the read timeout: one call, not retried, the rider still gets the plan",
        "prose_then_forced": "A prose answer instead of the Plan: the SDK's forced structured-output request "
        "(toolChoice any, a user instruction) is accepted, the plan is the model's",
        "human_moment_yes": "After dark, the rider says yes: asked once, the resumed pass retried by the gates, sent",
        "human_moment_no": "After dark, the rider says no: asked once, the Plan on file, nothing sent",
    }
    for name, run in runs.items():
        s = run.summary()
        lines += [f"## {titles[name]}", "", "| Request | Turns | Accepted | Model replied |", "|---|---|---|---|"]
        for e in run.fake.exchanges:
            turns = " ".join(r[0] for r in e.roles)  # u a u a
            reply = e.reply if not e.detail else f"{e.reply}: {e.detail}"
            choice = run.requests[e.request_no - 1].get("toolConfig", {}).get("toolChoice", {})
            forced = "" if "auto" in choice or not choice else f" (toolChoice {next(iter(choice))})"
            lines.append(f"| {e.request_no} | {turns}{forced} | {'yes' if e.accepted else 'no'} | {reply} |")
        asked = f"; the rider asked {s['interrupts_raised']} time(s)" if "interrupts_raised" in s else ""
        lines += [
            "",
            f"Outcome: composed by {s['composed_by']} ({s['stop_reason']}); {s['model_calls']} model call(s), "
            f"{s['requests']} request(s), {s['rejected_by_converse_rules']} rejected by the Converse rules; "
            f"hook cancels {s['hook_cancels']}, Guides before the tool {s['guide_before_tool']}, after the model "
            f"{s['guide_after_model']}{asked}.",
        ]
        if s["reason"]:
            lines.append(f"Reason: {s['reason']}")
        lines.append("")
    lines += [
        "Turns are the roles in the request, first to last (u user, a assistant). A Guide after the model",
        "discards the assistant turn and appends the reason as a user turn, so the retry after a tool result",
        "has two user turns in a row, and a second Guide makes three. The cap wrapper (`budget.py`) makes",
        "the request sendable before the adapter sees it: the SDK's own neutral assistant turn after the tool",
        "result, ahead of time (the SDK inserts it only after Bedrock has rejected a request once per process",
        "and model id), and adjacent user text turns folded into one (the SDK has no answer for those). The",
        "stand-in enforces the strict reading of the Converse rules; a model that accepts more simply never",
        "rejects, and the passes cost nothing there.",
        "",
    ]
    return "\n".join(lines)
