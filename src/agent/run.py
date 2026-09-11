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
from agent.outage_parser import parse_and_validate
from agent.schema import Plan, normalize_option
from bart import BartClient
from policy import Decision, Outage, Trip, assess, assess_condition


@dataclass
class Verification:
    option_ok: bool
    minutes_ok: bool
    corrections: list[str] = field(default_factory=list)


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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    final = plan.model_copy(
        update={
            "option": top if top is not None else plan.option,
            "added_minutes": top_minutes,
            "affected": affected,
        }
    )
    return final, Verification(option_ok, minutes_ok, corrections)


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
    return run_with_decision(trip, raw, parsed, decision, when, model, config=config)


def run_with_decision(
    trip: Trip,
    raw: str,
    parsed_label: dict[str, Any],
    decision: Decision,
    when: datetime,
    model: Any,
    *,
    config: AgentConfig | None = None,
) -> RunReport:
    trip_dict = {
        "origin": trip.origin,
        "dest": trip.dest,
        "needs": sorted(trip.needs),
        "when": when.isoformat(),
    }
    fragment = raw
    base = config or AgentConfig()
    cfg = AgentConfig(
        hooks_enabled=base.hooks_enabled,
        steering_enabled=base.steering_enabled,
        structured_output=True,
        required_option=decision.top_option,
        system_prompt=base.system_prompt,
    )
    built: BuiltAgent = build_agent(model, config=cfg)

    error = None
    model_plan: Plan | None = None
    try:
        result = built(prompt_for(trip, raw, parsed_label, when))
        if isinstance(result.structured_output, Plan):
            model_plan = result.structured_output
        else:
            error = "agent ended without a Plan"
    except StructuredOutputException as exc:
        error = f"no Plan produced: {exc}"

    final_plan, verification = verify_plan(model_plan, decision) if model_plan else (None, None)
    mechanisms = {
        "hook_cancellations": len(built.validator_hook.cancelled) if built.validator_hook else 0,
        "hook_cancelled_calls": built.validator_hook.cancelled if built.validator_hook else [],
        "steering_guides": len(built.option_steering.guides) if built.option_steering else 0,
        "steering_guide_details": built.option_steering.guides if built.option_steering else [],
        "text_rewrites": len(built.steering.rewrites) if built.steering else 0,
        "model_calls": len(getattr(model, "calls", [])) or 0,
        "ablated": not (cfg.hooks_enabled and cfg.steering_enabled),
    }
    return RunReport(
        fragment,
        trip_dict,
        parsed_label,
        decision.as_dict(),
        model_plan.model_dump() if model_plan else None,
        final_plan.model_dump() if final_plan else None,
        verification,
        mechanisms,
        error,
    )
