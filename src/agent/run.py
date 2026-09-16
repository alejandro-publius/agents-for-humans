"""Run the agent for one rider trip and one outage fragment, with code deciding before and after.

Order of decisions:
    1. Code parses the fragment and validates it against the KB (regex path; the model parser is
       used by the outage_parse eval).
    2. Code runs the policy engine: affected?, condition, documented option, ranked options,
       minutes, flags. This is the ground truth the steering handler enforces.
    3. The model runs with the tools and must end with a Plan.
    4. Code verifies the Plan against the decision: the option must be the top feasible option and
       the minutes must be the computed ones. Disagreements are corrected and recorded; the model's
       original proposal is kept for the evals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from strands.types.exceptions import StructuredOutputException

from agent.core import AgentConfig, BuiltAgent, build_agent
from agent.decision_card import build_card, case_key, decision_flags
from agent.outage_parser import parse_and_validate
from agent.schema import Plan, normalize_option
from agent.scrub import unknown_station_codes
from bart import BartClient
from policy import Decision, Outage, Trip, assess, assess_condition


@dataclass
class Verification:
    option_ok: bool
    minutes_ok: bool
    corrections: list[str] = field(default_factory=list)
    unknown_stations: list[str] = field(default_factory=list)


@dataclass
class RunReport:
    fragment: str
    trip: dict[str, Any]
    parsed: dict[str, Any]
    decision: dict[str, Any]
    model_plan: dict[str, Any] | None
    final_plan: dict[str, Any] | None
    verification: Verification | None
    mechanisms: dict[str, Any]
    error: str | None = None
    interrupt: dict[str, Any] | None = None  # set while the run is paused for a rider decision
    card: dict[str, Any] | None = None  # the decision card shown to the rider, when one exists
    _built: Any = field(default=None, repr=False, compare=False)
    _decision: Any = field(default=None, repr=False, compare=False)

    @property
    def paused(self) -> bool:
        return self.interrupt is not None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("_built", None)
        data.pop("_decision", None)
        return data


def verify_plan(plan: Plan, decision: Decision) -> tuple[Plan, Verification]:
    """Code decides: option and minutes come from the policy engine, whatever the model said."""
    corrections: list[str] = []
    proposed = normalize_option(plan.option)
    top = decision.top_option
    option_ok = proposed == top
    if not option_ok and top is not None:
        corrections.append(f"option {proposed!r} replaced with policy top option {top!r}")
    top_minutes = next((o.added_minutes for o in decision.ranked_options if o.option == top), None)
    minutes_ok = plan.added_minutes == top_minutes
    if not minutes_ok:
        corrections.append(f"added_minutes {plan.added_minutes!r} replaced with computed {top_minutes!r}")
    affected = bool(decision.affected)
    if plan.affected != affected:
        corrections.append(f"affected {plan.affected!r} replaced with policy {affected!r}")
    update: dict[str, Any] = {
        "option": top if top is not None else plan.option,
        "added_minutes": top_minutes,
        "affected": affected,
    }
    unknown = unknown_station_codes(plan.message, *plan.steps)
    if unknown:
        # A station the KB does not know never reaches the rider: fall back to BART's own text.
        documented = (decision.documented_option or {}).get(
            "text"
        ) or "Contact the Station Agent for assistance."
        update["steps"] = [documented]
        update["message"] = documented
        corrections.append(f"message and steps replaced: unknown station code(s) {unknown}")
    final = plan.model_copy(update=update)
    return final, Verification(option_ok, minutes_ok, corrections, unknown_stations=unknown)


def prompt_for(trip: Trip, raw: str, parsed: dict[str, Any], when: datetime) -> str:
    return (
        f"Outage: {raw} (station {parsed['station_abbr']}, elevator {parsed['kb_elevator']!r}). "
        f"Rider trip: {trip.origin} to {trip.dest}, needs {sorted(trip.needs)}, at {when.isoformat()}."
    )


def run_one(
    trip: Trip,
    fragment: str,
    when: datetime,
    model: Any,
    *,
    config: AgentConfig | None = None,
    client: BartClient | None = None,
) -> RunReport:
    client = client or BartClient()
    parsed = parse_and_validate(fragment)
    trip_dict = {
        "origin": trip.origin,
        "dest": trip.dest,
        "needs": sorted(trip.needs),
        "when": when.isoformat(),
    }
    if not parsed.valid:
        problems = "; ".join(parsed.problems)
        return RunReport(fragment, trip_dict, parsed.as_label(), {}, None, None, None, {}, error=problems)

    decision = assess(trip, Outage(parsed.station_abbr, parsed.kb_elevator, fragment), when, client)
    return run_with_decision(trip, fragment, parsed.as_label(), decision, when, model, config=config)


def run_condition(
    trip: Trip,
    station_abbr: str,
    elevator: str,
    situation: str,
    when: datetime,
    model: Any,
    *,
    config: AgentConfig | None = None,
    client: BartClient | None = None,
    tools: list[Any] | None = None,
) -> RunReport:
    """Run for a (station, elevator, condition) triple the caller already knows (policy-agreement eval)."""
    decision = assess_condition(trip, station_abbr, elevator, situation, when, client)
    parsed = {
        "station_abbr": station_abbr,
        "level_from": None,
        "level_to": None,
        "platform_label": None,
        "kb_elevator": elevator,
    }
    raw = f"{station_abbr}: {elevator} ({situation})"
    return run_with_decision(trip, raw, parsed, decision, when, model, config=config, tools=tools)


def run_with_decision(
    trip: Trip,
    raw: str,
    parsed_label: dict[str, Any],
    decision: Decision,
    when: datetime,
    model: Any,
    *,
    config: AgentConfig | None = None,
    tools: list[Any] | None = None,
) -> RunReport:
    trip_dict = {
        "origin": trip.origin,
        "dest": trip.dest,
        "needs": sorted(trip.needs),
        "when": when.isoformat(),
    }
    base = config or AgentConfig()
    flags = decision_flags(decision) if base.steering_enabled else []
    card = build_card(decision) if flags else {}
    cfg = AgentConfig(
        hooks_enabled=base.hooks_enabled,
        steering_enabled=base.steering_enabled,
        structured_output=True,
        required_option=decision.top_option,
        case_key=case_key(decision.station, decision.elevator, decision.condition),
        decision_flags=flags,
        decision_card=card,
        decisions=base.decisions,
        session_id=base.session_id,
        session_dir=base.session_dir,
        system_prompt=base.system_prompt,
    )
    built: BuiltAgent = build_agent(model, config=cfg, tools=tools)
    report = RunReport(
        fragment=raw,
        trip=trip_dict,
        parsed=parsed_label,
        decision=decision.as_dict(),
        model_plan=None,
        final_plan=None,
        verification=None,
        mechanisms={},
        card=card or None,
        _built=built,
        _decision=decision,
    )
    return _drive(report, lambda: built(prompt_for(trip, raw, parsed_label, when)))


def _drive(report: RunReport, invoke) -> RunReport:
    """Run (or resume) the agent via ``invoke`` and fill the report from the outcome."""
    built: BuiltAgent = report._built
    decision: Decision = report._decision
    model = built.agent.model
    error = None
    model_plan: Plan | None = None
    interrupt = None
    try:
        result = invoke()
        if result.stop_reason == "interrupt" and result.interrupts:
            first = result.interrupts[0]
            interrupt = {"id": first.id, "name": first.name, "reason": first.reason}
        elif isinstance(result.structured_output, Plan):
            model_plan = result.structured_output
        else:
            error = "agent ended without a Plan"
    except StructuredOutputException as exc:
        error = f"no Plan produced: {exc}"

    final_plan, verification = verify_plan(model_plan, decision) if model_plan else (None, None)
    steering = built.option_steering
    report.mechanisms = {
        "hook_cancellations": len(built.validator_hook.cancelled) if built.validator_hook else 0,
        "hook_cancelled_calls": built.validator_hook.cancelled if built.validator_hook else [],
        "steering_guides": len(steering.guides) if steering else 0,
        "steering_guide_details": steering.guides if steering else [],
        "steering_interrupts": len(steering.interrupts) if steering else 0,
        "text_rewrites": len(built.steering.rewrites) if built.steering else 0,
        "model_calls": len(getattr(model, "calls", [])) or 0,
        "ablated": not (built.config.hooks_enabled and built.config.steering_enabled),
    }
    report.model_plan = model_plan.model_dump() if model_plan else None
    report.final_plan = final_plan.model_dump() if final_plan else None
    report.verification = verification
    report.error = error
    report.interrupt = interrupt
    return report


def reopen_paused_run(
    trip: Trip,
    raw: str,
    parsed_label: dict[str, Any],
    decision: Decision,
    interrupt_id: str,
    model: Any,
    *,
    config: AgentConfig,
) -> RunReport:
    """Rebuild a paused run from its persisted session (config.session_id) so it can be resumed later,
    for example from the rider app after the rider answers the decision card."""
    if not config.session_id:
        raise ValueError("reopening a paused run needs config.session_id")
    flags = decision_flags(decision)
    card = build_card(decision) if flags else {}
    cfg = AgentConfig(
        hooks_enabled=config.hooks_enabled,
        steering_enabled=config.steering_enabled,
        structured_output=True,
        required_option=decision.top_option,
        case_key=case_key(decision.station, decision.elevator, decision.condition),
        decision_flags=flags,
        decision_card=card,
        decisions=config.decisions,
        session_id=config.session_id,
        session_dir=config.session_dir,
        system_prompt=config.system_prompt,
    )
    built = build_agent(model, config=cfg)
    return RunReport(
        fragment=raw,
        trip={"origin": trip.origin, "dest": trip.dest, "needs": sorted(trip.needs), "when": None},
        parsed=parsed_label,
        decision=decision.as_dict(),
        model_plan=None,
        final_plan=None,
        verification=None,
        mechanisms={},
        interrupt={"id": interrupt_id, "name": "steering_input_draft_message", "reason": None},
        card=card or None,
        _built=built,
        _decision=decision,
    )


def resume_run(report: RunReport, answer: str) -> RunReport:
    """Answer a paused run ('accept' or 'decline'). The answer is remembered for the case key in
    agent state (persisted by the session manager) and in the caller's decisions dict."""
    if not report.paused or report._built is None:
        raise ValueError("report is not paused")
    built: BuiltAgent = report._built
    if built.option_steering is not None:
        built.option_steering.remember(built.agent, answer)
    interrupt_id = report.interrupt["id"]
    response = answer == "accept"
    report.interrupt = None
    return _drive(
        report,
        lambda: built.agent([{"interruptResponse": {"interruptId": interrupt_id, "response": response}}]),
    )
