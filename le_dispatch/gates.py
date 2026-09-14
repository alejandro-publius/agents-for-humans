"""Two-stage enforcement: before the tool, after the model.

Stage 0, KBHook (BeforeToolCallEvent): any tool call naming a station or
elevator that is not in the frozen KB is cancelled. The cancel text lands in
the tool result with error status, visible to the model.

Stage 1, PlanGateHandler.steer_before_tool: the draft_plan call must carry
the policy engine's top feasible option. Anything else is Guided: the call is
cancelled and the reason is fed back; the model retries.

Stage 2, PlanGateHandler.steer_after_model: when the model emits the final
structured Plan (Strands' structured-output tool, named after the Plan
class), the plan's station and elevator are checked against the KB and the
decision, its option against the policy engine's top option, and its minutes
against the policy engine's minutes. On mismatch the response is discarded
(Guide) and the model is called again with the reason; on match, Proceed.

The handler fails closed: an unexpected exception inside a gate returns
Guide, never Proceed. Models propose, code decides.

Every gate has an off switch (`build_agent(disabled={...})`, names in
GATES) used only by the ablation study, which removes one gate at a time
and counts what then reaches the rider (ablation.py). Production never
passes `disabled`.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from typing import Any

from strands import Agent
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.vended_plugins.steering.core.action import Guide, Proceed
from strands.vended_plugins.steering.core.handler import SteeringHandler

from . import tracing
from .budget import BudgetedModel, expected_cap
from .interfaces import KBSet, PolicyCallable, PolicyDecision, Trip
from .messages import approval_hint, composed_plan, is_approved
from .plan import PLAN_TOOL_NAME, Plan, make_tools

STATION_FIELDS = ("station", "origin", "destination")
ELEVATOR_FIELDS = ("elevator",)

# the five gates, in the order a run meets them; ablation.py removes them one at a time
GATES = ("kb_hook", "option_gate", "plan_fields", "plan_prose", "plan_approval")

# Prose checks on the rider message: the model never computes minutes, not even
# in a sentence, and never names a station or elevator code outside the KB.
MINUTES_RE = re.compile(r"\b(\d+)\s*(?:more\s+)?(?:min(?:ute)?s?)\b", re.I)
CODE_RE = re.compile(r"\b(?=[A-Z0-9]*[A-Z])([A-Z0-9]{4})(-E\d+)?\b")
PROSE_ALLOWLIST = frozenset({"BART", "MUNI", "SFMTA", "ADA", "SFO", "OAK", "UTC", "PDT", "PST", "TODO", "NONE", "OPEN"})
# label words that, when they appear in the sentence, must be the plan's option ("transit" is left out:
# "AC Transit" is a bus operator and appears legitimately in other options' sentences)
LABEL_WORDS = {
    "alternate_elevator": ("alternate_elevator", "alternate elevator"),
    "backtracking": ("backtracking", "backtrack"),
    "mitigation_trip": ("mitigation_trip", "mitigation trip"),
    "mitigation_shuttle": ("mitigation_shuttle", "mitigation shuttle"),
}


def prose_findings(
    message: Any, kb: KBSet, expected_minutes: int | None, expected_option: str | None = None
) -> list[str]:
    """Problems in free text: minutes that are not the policy engine's, codes
    that are not in the KB, and a BART option named in the sentence that is
    not the plan's option. Deterministic, no model."""
    if not isinstance(message, str):
        return []
    problems = []
    low = message.lower()
    if expected_option is not None:
        for label, words in LABEL_WORDS.items():
            if label != expected_option and any(w in low for w in words):
                problems.append(f"rider_message names the {label!r} option; the plan's option is {expected_option!r}")
    for m in MINUTES_RE.finditer(message):
        stated = int(m.group(1))
        if stated != expected_minutes:
            problems.append(f"rider_message states {stated} minutes; the policy engine says {expected_minutes!r}")
    for m in CODE_RE.finditer(message):
        code, suffix = m.group(1), m.group(2)
        if suffix:
            if not kb.has_elevator(code + suffix):
                problems.append(f"rider_message names elevator {code + suffix!r}, not in the knowledge base")
        elif code not in PROSE_ALLOWLIST and not kb.has_station(code):
            problems.append(f"rider_message names {code!r}, not a station in the knowledge base")
    return problems


_SEQ = itertools.count(1)


@dataclass
class GateEvent:
    kind: str
    tool: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)
    seq: int = field(default_factory=lambda: next(_SEQ))  # process-wide order of occurrence


class KBHook(HookProvider):
    """Deterministic KB gate. Cancels any tool call that names an unknown
    station or elevator, before the tool runs."""

    def __init__(
        self,
        kb: KBSet,
        tools: tuple[str, ...] = (PLAN_TOOL_NAME, Plan.__name__),
        *,
        enabled: bool = True,
        decision: PolicyDecision | None = None,
    ):
        self.kb = kb
        self.tools = tools
        self.enabled = enabled  # False only in the ablation study
        self.decision = decision  # when known, the cancel message names the affected station and elevator
        self.events: list[GateEvent] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.check)
        registry.add_callback(AfterToolCallEvent, self.record)

    def record(self, event: AfterToolCallEvent) -> None:
        """After the draft tool ran (not cancelled, not failed): one event, so the evidence packet shows
        every model action, the accepted call included, not only the ones a gate stopped."""
        name = event.tool_use["name"]
        if name != PLAN_TOOL_NAME or event.cancel_message or event.exception:
            return
        result = event.result or {}
        if isinstance(result, dict) and result.get("status") == "error":
            return
        args = event.tool_use.get("input") or {}
        self.events.append(GateEvent(tracing.TOOL_RAN, name, "tool ran with these arguments", dict(args)))

    def check(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        if name not in self.tools or not self.enabled:
            return
        args = event.tool_use.get("input") or {}
        if not isinstance(args, dict):
            return
        problems = []
        for f in STATION_FIELDS:
            if f in args and not self.kb.has_station(args[f]):
                problems.append(f"{f}={args[f]!r} is not a station in the knowledge base")
        for f in ELEVATOR_FIELDS:
            if f in args and not self.kb.has_elevator(args[f]):
                problems.append(f"{f}={args[f]!r} is not an elevator in the knowledge base")
        if problems:
            right = ""
            if self.decision is not None and self.decision.affected:
                right = (
                    f"; the affected station is {self.decision.station!r} and the elevator that is out is "
                    f"{self.decision.elevator!r}"
                )
            reason = (
                "Cancelled: "
                + "; ".join(problems)
                + right
                + ". Use only stations and elevators from the knowledge base."
            )
            event.cancel_tool = reason
            self.events.append(GateEvent(tracing.HOOK_CANCEL, name, reason, dict(args)))
            tracing.add_span_event(tracing.HOOK_CANCEL, tool=name, reason=reason)

    @property
    def cancels(self) -> int:
        return sum(1 for e in self.events if e.kind == tracing.HOOK_CANCEL)


class PlanGateHandler(SteeringHandler):
    """Option-order gate before the tool, plan gate after the model."""

    name = "plan_gate"

    def __init__(
        self,
        *,
        kb: KBSet,
        policy: PolicyCallable,
        trip: Trip,
        plan_tool: str = PLAN_TOOL_NAME,
        plan_model: type[Plan] = Plan,
        approved_messages: bool = True,
        disabled: frozenset[str] = frozenset(),
    ):
        super().__init__()
        self.kb = kb
        self.policy = policy
        self.trip = trip
        self.plan_tool = plan_tool
        self.plan_model = plan_model
        self.approved_messages = approved_messages  # strict: the rider message must be a code-composed sentence
        unknown = set(disabled) - set(GATES)
        if unknown:
            raise ValueError(f"unknown gate(s) {sorted(unknown)}; known: {GATES}")
        self.disabled = frozenset(disabled)  # ablation only
        self.events: list[GateEvent] = []
        self._decision: PolicyDecision | None = None

    @property
    def decision(self) -> PolicyDecision:
        if self._decision is None:
            self._decision = self.policy(self.trip)
        return self._decision

    def count(self, kind: str) -> int:
        return sum(1 for e in self.events if e.kind == kind)

    # Stage 1: before the tool ------------------------------------------------
    async def steer_before_tool(self, *, agent: Agent, tool_use: Any, **kwargs: Any):
        name = tool_use["name"]
        if name != self.plan_tool:
            return Proceed(reason="not a plan tool")
        if "option_gate" in self.disabled:
            return Proceed(reason="option gate disabled (ablation)")
        try:
            args = tool_use.get("input") or {}
            option = args.get("option")
            top = self.decision.top_option
            if not self.decision.affected:
                reason = "The policy engine says this trip is not affected; do not draft a plan."
                return self._guide_before(name, reason, args)
            if not self.kb.has_label(option):
                reason = (
                    f"{option!r} is not a BART option label. Use exactly one of: "
                    f"{', '.join(self.kb.option_labels)}. The policy engine's top option here is {top!r}."
                )
                return self._guide_before(name, reason, args)
            if option != top:
                reason = (
                    f"BART's published order puts {top!r} first for this outage; {option!r} is not the "
                    f"policy engine's top feasible option. Call {self.plan_tool} again with option={top!r}."
                )
                return self._guide_before(name, reason, args)
            return Proceed(reason="option matches the policy engine's top feasible option")
        except Exception as exc:  # fail closed
            return self._guide_before(name, f"gate error, refusing to proceed: {exc!r}", {})

    def _guide_before(self, tool: str, reason: str, args: dict[str, Any]) -> Guide:
        self.events.append(GateEvent(tracing.GUIDE_BEFORE, tool, reason, dict(args)))
        tracing.add_span_event(tracing.GUIDE_BEFORE, tool=tool, reason=reason)
        return Guide(reason=reason)

    # Stage 2: after the model -------------------------------------------------
    async def steer_after_model(self, *, agent: Agent, message: Any, stop_reason: str, **kwargs: Any):
        try:
            plan = extract_plan(message, self.plan_model.__name__)
            if plan is None:
                return Proceed(reason="no final plan in this message")
            problems = self.check_plan(plan)
            if problems:
                reason = (
                    "Plan rejected: " + "; ".join(problems) + ". Re-issue the Plan with the policy engine's values."
                )
                self.events.append(GateEvent(tracing.GUIDE_AFTER, self.plan_model.__name__, reason, plan))
                tracing.add_span_event(tracing.GUIDE_AFTER, reason=reason, **_flat(plan))
                return Guide(reason=reason)
            self.events.append(GateEvent(tracing.PROCEED_AFTER, self.plan_model.__name__, "plan matches", plan))
            tracing.add_span_event(tracing.PROCEED_AFTER, **_flat(plan))
            return Proceed(reason="plan matches the policy engine and the knowledge base")
        except Exception as exc:  # fail closed
            reason = f"gate error, discarding response: {exc!r}"
            self.events.append(GateEvent(tracing.GUIDE_AFTER, self.plan_model.__name__, reason, {}))
            tracing.add_span_event(tracing.GUIDE_AFTER, reason=reason)
            return Guide(reason=reason)

    def check_plan(self, plan: dict[str, Any]) -> list[str]:
        """Every check is code against the decision; none consults a model."""
        d = self.decision
        problems = []
        station, elevator, option = plan.get("station"), plan.get("elevator"), plan.get("option")
        expected_minutes = d.minutes_for(d.top_option)
        if "plan_fields" not in self.disabled:
            # every reason names the right value, so a model can repair from this gate alone
            # (the ablation study found that the KB reasons did not, and the wrong-elevator persona never converged
            # once the hook was removed)
            if not self.kb.has_station(station):
                problems.append(
                    f"station {station!r} is not in the knowledge base; the affected station is {d.station!r}"
                )
            elif d.station and station != d.station:
                problems.append(f"station {station!r} is not the affected station {d.station!r}")
            if not self.kb.has_elevator(elevator):
                problems.append(
                    f"elevator {elevator!r} is not in the knowledge base; the elevator that is out is {d.elevator!r}"
                )
            elif d.elevator and elevator != d.elevator:
                problems.append(f"elevator {elevator!r} is not the elevator that is out ({d.elevator!r})")
            if not d.affected:
                problems.append("the policy engine says this trip is not affected")
            elif option != d.top_option:
                problems.append(f"option {option!r} is not the policy engine's top feasible option {d.top_option!r}")
            if plan.get("added_minutes") != expected_minutes:
                problems.append(
                    f"added_minutes {plan.get('added_minutes')!r} did not come from the policy engine "
                    f"(expected {expected_minutes!r})"
                )
        if "plan_prose" not in self.disabled:
            problems.extend(prose_findings(plan.get("rider_message"), self.kb, expected_minutes, d.top_option))
        status = plan.get("status", "send")
        if "plan_approval" not in self.disabled and self.approved_messages:
            if not is_approved(plan.get("rider_message"), d, status):
                problems.append(approval_hint(d, status))
        return problems


def _flat(plan: dict[str, Any]) -> dict[str, Any]:
    return {f"plan.{k}": v for k, v in plan.items() if k in ("station", "elevator", "option", "added_minutes")}


_JSON_RE = re.compile(r"\{.*\}", re.S)


def extract_plan(message: Any, plan_tool_name: str) -> dict[str, Any] | None:
    """Find the final plan in an assistant message: the structured-output tool
    call first, then a JSON object in text for agents without structured output."""
    content = message.get("content", []) if isinstance(message, dict) else []
    for block in content:
        if isinstance(block, dict) and "toolUse" in block:
            tu = block["toolUse"]
            if tu.get("name") == plan_tool_name and isinstance(tu.get("input"), dict):
                return dict(tu["input"])
    for block in content:
        if isinstance(block, dict) and "text" in block:
            m = _JSON_RE.search(block["text"])
            if m:
                try:
                    obj = json.loads(m.group(0))
                except ValueError:
                    continue
                if isinstance(obj, dict) and "option" in obj and "station" in obj:
                    return obj
    return None


SYSTEM_PROMPT = (
    "You help a BART rider who depends on elevators. Use draft_plan with a station and elevator "
    "from the knowledge base and BART's top option, then return the Plan. Never invent stations, "
    "never compute minutes, never decide affectedness yourself; copy the policy engine's values. "
    "The rider_message must be one of the approved_messages returned by draft_plan, verbatim."
)


@dataclass
class AgentBundle:
    agent: Agent
    hook: KBHook
    gate: PlanGateHandler | None
    trip: Trip
    kb: KBSet | None = None
    policy: PolicyCallable | None = None

    @property
    def decision(self) -> PolicyDecision:
        if self.gate is not None:
            return self.gate.decision
        assert self.policy is not None
        return self.policy(self.trip)


@dataclass
class DeliveryOutcome:
    """What reached the rider, and who wrote it."""

    plan: dict[str, Any] | None
    composed_by: str  # "model" | "code" | "none"
    stop_reason: str
    model_turns: int | None = None
    reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)  # what the decision cost: model calls, tokens, cycles


def run_usage(bundle: AgentBundle) -> dict[str, int]:
    """What one run cost, from Strands' own metrics on the agent: the model calls the cap wrapper counted,
    the tokens the provider reported, the event-loop cycles."""
    metrics = getattr(bundle.agent, "event_loop_metrics", None)
    acc = dict(getattr(metrics, "accumulated_usage", {}) or {})
    return {
        "model_calls": int(getattr(bundle.agent.model, "calls", 0) or 0),
        "input_tokens": int(acc.get("inputTokens", 0) or 0),
        "output_tokens": int(acc.get("outputTokens", 0) or 0),
        "total_tokens": int(acc.get("totalTokens", 0) or 0),
        "cycles": int(getattr(metrics, "cycle_count", 0) or 0),
    }


def trip_prompt(trip: Trip, decision: PolicyDecision | None = None) -> str:
    """What the model is told: the trip and the outage by name, so a live model has something to call
    draft_plan with. The scripted models ignore it; a real one and the wire stand-in read it."""
    if decision is not None and decision.affected:
        outage = f"Elevator {decision.elevator} at {decision.station} is out."
    else:
        outage = "Elevators out: " + (", ".join(trip.outages) if trip.outages else "none") + "."
    return (
        f"Plan my trip from {trip.origin} to {trip.destination}. {outage} Use draft_plan with that station and "
        "elevator, then return the Plan with one of its approved_messages."
    )


def deliver(bundle: AgentBundle, prompt: str | None = None, *, max_turns: int = 8) -> DeliveryOutcome:
    """Run the gated agent under a Strands turn limit. If the model never
    produces an approved plan (limit reached, structured output missing, or
    an exception), code composes the plan from the policy decision, so the
    rider always gets a plan and the model can only delay it, never block it
    or corrupt it. An unaffected trip never runs the model: there is nothing
    to send, and the runtime reports it as quiet."""
    if not bundle.decision.affected:
        tracing.add_span_event("delivery.quiet", reason="the policy engine says this trip is not affected")
        return DeliveryOutcome(None, "none", "not_affected", 0, "the policy engine says this trip is not affected")
    if prompt is None:
        prompt = trip_prompt(bundle.trip, bundle.decision)
    try:
        with expected_cap():
            result = bundle.agent(prompt, limits={"turns": max_turns})
    except Exception as exc:  # a run that ends without a plan: the rider still gets one
        tracing.add_span_event("delivery.composed_by_code", reason=repr(exc))
        return DeliveryOutcome(
            composed_plan(bundle.decision), "code", "exception", None, repr(exc), usage=run_usage(bundle)
        )
    calls = getattr(bundle.agent.model, "calls", None)
    usage = run_usage(bundle)
    plan = result.structured_output
    if isinstance(plan, Plan):
        # the last line: the same checks once more, here, before anything reaches the rider, so a gate the SDK
        # did not invoke (a plumbing change, a future version) cannot leak; it honours the ablation switches
        problems = bundle.gate.check_plan(plan.model_dump()) if bundle.gate is not None else []
        if problems:
            reason = "final check failed: " + "; ".join(problems)
            tracing.add_span_event("delivery.final_check_failed", reason=reason)
            tracing.add_span_event("delivery.composed_by_code", reason=reason)
            return DeliveryOutcome(composed_plan(bundle.decision), "code", "final_check", calls, reason, usage=usage)
        return DeliveryOutcome(plan.model_dump(), "model", str(result.stop_reason), calls, usage=usage)
    if result.stop_reason == "interrupt":
        return DeliveryOutcome(None, "none", "interrupt", calls, "paused for the rider", usage=usage)
    tracing.add_span_event("delivery.composed_by_code", reason=str(result.stop_reason))
    return DeliveryOutcome(
        composed_plan(bundle.decision),
        "code",
        str(result.stop_reason),
        calls,
        f"model did not produce an approved plan within {max_turns} turns",
        usage=usage,
    )


def build_agent(
    model: Any,
    kb: KBSet,
    policy: PolicyCallable,
    trip: Trip,
    *,
    steering: bool = True,
    extra_plugins: tuple[Any, ...] = (),
    extra_hooks: tuple[Any, ...] = (),
    system_prompt: str = SYSTEM_PROMPT,
    session_manager: Any = None,
    approved_messages: bool = True,
    max_model_calls: int = 24,
    disabled: frozenset[str] = frozenset(),
    retry_strategy: Any = None,
) -> AgentBundle:
    """The full stack: KB hook, both steering gates, structured output.
    steering=False is the no_steering ablation (hook and structured output stay).
    disabled: gates switched off by name (GATES), for the ablation study only.
    session_manager: any Strands session manager (FileSessionManager,
    S3SessionManager, ...); it persists messages, agent.state and a pending
    interrupt, so a paused run resumes in another process.
    max_model_calls: a per-run hard cap on model calls (Strands' after-model
    retry loop is unbounded; see budget.py); when it trips, deliver()
    composes the plan in code.
    retry_strategy: a Strands ModelRetryStrategy for throttles; None keeps the
    SDK's default (six attempts, 4 s to 64 s of backoff). A throttled attempt
    counts against max_model_calls."""
    model = BudgetedModel(model, max_model_calls, label=f"run {trip.case_key}")
    hook = KBHook(kb, enabled="kb_hook" not in disabled, decision=policy(trip))
    gate = (
        PlanGateHandler(kb=kb, policy=policy, trip=trip, approved_messages=approved_messages, disabled=disabled)
        if steering
        else None
    )
    plugins = ([gate] if gate else []) + list(extra_plugins)
    kwargs: dict[str, Any] = {}
    if session_manager is not None:
        kwargs["session_manager"] = session_manager
    if retry_strategy is not None:  # Agent(retry_strategy=None) would switch retries off; leave the default alone
        kwargs["retry_strategy"] = retry_strategy
    agent = Agent(
        model=model,
        tools=make_tools(kb, policy, trip),
        hooks=[hook, *extra_hooks],
        plugins=plugins,
        structured_output_model=Plan,
        system_prompt=system_prompt,
        callback_handler=None,
        **kwargs,
    )
    return AgentBundle(agent=agent, hook=hook, gate=gate, trip=trip, kb=kb, policy=policy)
