"""The evidence packet: everything a rider, an operator or a judge needs to
audit one decision after the fact, in one file.

A packet holds the trip and the outage, the policy engine's decision (the
code that decided), every gate event in order (what the model tried and
what stopped it), the decision card if the rider was asked, the final plan
that reached the rider, the gate span events from the trace, and a
sequence diagram of the run. The JSON is the record; the markdown is the
same record for humans. No timestamps, so a rerun on the same inputs is
byte-identical and diffable.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from . import tracing
from .gates import AgentBundle, GateEvent, run_usage
from .interfaces import PolicyDecision, Trip, data_source, source_label
from .interrupts import DecisionCard

FRIENDLY = {
    tracing.TOOL_RAN: "draft_plan ran (the policy engine's values came back)",
    tracing.HOOK_CANCEL: "KB hook cancelled the tool call",
    tracing.GUIDE_BEFORE: "steering guided the tool call (wrong option)",
    tracing.GUIDE_AFTER: "steering discarded the model's plan",
    tracing.PROCEED_AFTER: "steering accepted the model's plan",
    tracing.INTERRUPT_RAISED: "run paused for the rider",
    tracing.INTERRUPT_RESUMED: "rider answered, run resumed",
}


TIMESTAMP_KEYS = ("created_at", "answered_at")


def _scrub(obj: Any) -> Any:
    """Drop wall-clock fields so a rerun on the same inputs is byte-identical."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in TIMESTAMP_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def build_packet(
    *,
    trip: Trip,
    decision: PolicyDecision,
    bundle: AgentBundle,
    events: list[GateEvent],
    plan: dict[str, Any] | None,
    card: DecisionCard | None = None,
    answer: bool | None = None,
    trace_events: list[dict[str, Any]] | None = None,
    provenance: str | None = None,
    note: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`note`, when the rider wrote one: {"text", "constraints", "read_by"} as the runtime reports it."""
    return _scrub(
        {
            "packet": "last-elevator evidence packet v1",
            "provenance": {
                "run": provenance if provenance is not None else f"scripted model, {source_label()}",
                "claimable": False,  # a demo run is never a result, whatever KB it read
                "source": data_source(),
            },
            "trip": asdict(trip),
            "note": note,
            "decision": decision.to_dict(),
            "gate_events": [
                {
                    "kind": e.kind,
                    "what": FRIENDLY.get(e.kind, e.kind),
                    "tool": e.tool,
                    "reason": e.reason,
                    "detail": e.detail,
                }
                for e in events
            ],
            "decision_card": card.to_dict() if card else None,
            "rider_answer": answer,
            "final_plan": plan,
            "trace_events": [
                {"event": t["event"], "span": t["span"], "attributes": t["attributes"]} for t in trace_events or []
            ],
            "counts": {
                "hook_cancel": sum(1 for e in events if e.kind == tracing.HOOK_CANCEL),
                "guide_before_tool": sum(1 for e in events if e.kind == tracing.GUIDE_BEFORE),
                "guide_after_model": sum(1 for e in events if e.kind == tracing.GUIDE_AFTER),
                "proceed_after_model": sum(1 for e in events if e.kind == tracing.PROCEED_AFTER),
                "interrupts": sum(1 for e in events if e.kind == tracing.INTERRUPT_RAISED),
                "model_calls": getattr(bundle.agent.model, "calls", None),
            },
            "cost": run_usage(bundle),  # what this decision cost: model calls, tokens, cycles (from Strands' metrics)
        }
    )


def sequence_diagram(packet: dict[str, Any]) -> str:
    """A Mermaid sequence diagram of the run, one arrow per gate event."""
    lines = [
        "sequenceDiagram",
        "    participant M as Model (proposes)",
        "    participant H as KB hook",
        "    participant S as Steering gates",
        "    participant T as draft_plan (policy engine values)",
        "    participant R as Rider",
    ]
    for e in packet["gate_events"]:
        kind = e["kind"]
        if kind == tracing.HOOK_CANCEL:
            lines.append(f"    M->>H: draft_plan({_short(e['detail'])})")
            lines.append("    H-->>M: cancelled: not in the knowledge base")
        elif kind == tracing.GUIDE_BEFORE:
            lines.append(f"    M->>S: draft_plan({_short(e['detail'])})")
            lines.append("    S-->>M: guide: not BART's top option, retry")
        elif kind == tracing.TOOL_RAN:
            lines.append(f"    M->>T: draft_plan({_short(e['detail'])})")
            lines.append("    T-->>M: the policy engine's values and the approved sentences")
        elif kind == tracing.INTERRUPT_RAISED:
            lines.append("    S->>R: decision card (after dark or last train)")
        elif kind == tracing.INTERRUPT_RESUMED:
            lines.append(f"    R-->>S: answer {e['reason']}")
        elif kind == tracing.GUIDE_AFTER:
            lines.append(f"    M->>S: Plan({_short(e['detail'])})")
            lines.append("    S-->>M: discarded: does not match the policy engine, retry")
        elif kind == tracing.PROCEED_AFTER:
            lines.append(f"    M->>S: Plan({_short(e['detail'])})")
            lines.append("    S-->>R: plan delivered")
    if packet["final_plan"] and not any(e["kind"] == tracing.PROCEED_AFTER for e in packet["gate_events"]):
        lines.append("    M->>R: plan delivered")
    return "\n".join(lines)


def _short(detail: dict[str, Any]) -> str:
    keys = ("station", "elevator", "option", "added_minutes")
    parts = [f"{k}={detail[k]!r}" for k in keys if k in detail]
    return ", ".join(parts)


def render_markdown(packet: dict[str, Any]) -> str:
    t, d = packet["trip"], packet["decision"]
    lines = [
        "# Evidence packet",
        "",
        f"Provenance: {packet['provenance']['run']} (claimable: {packet['provenance']['claimable']}).",
        "",
        "## Trip and outage",
        "",
        f"Rider `{t['rider_id']}`, {t['origin']} to {t['destination']}, "
        f"elevators out: {', '.join(t['outages']) or 'none'}"
        + (", after dark" if t.get("after_dark") else "")
        + (", last train" if t.get("last_train") else "")
        + ".",
        "",
    ]
    if packet.get("note"):
        n = packet["note"]
        ruled = ", ".join(n.get("constraints") or []) or "nothing"
        lines += [
            "## The rider's own words",
            "",
            f"> {n['text']}",
            "",
            f"Read by the {n.get('read_by')} into the fixed vocabulary: {ruled} ruled out. Code applied it as "
            "feasibility only: BART's order among the rest stands, the minutes are the policy engine's"
            + (", and nothing was left, so the note was set aside" if d.get("note_set_aside") else "")
            + ".",
            "",
        ]
    lines += [
        "## What code decided (policy engine, no model)",
        "",
        f"Affected: {d['affected']} ({d.get('kind')}). Station {d.get('station')}, elevator {d.get('elevator')}. "
        f"Top option: `{d.get('top_option')}`. Source: {d.get('source_url') or 'n/a'}",
        "",
        "| Rank | Option | Feasible | Added minutes | Reason |",
        "|---|---|---|---|---|",
    ]
    for i, o in enumerate(d.get("ranked", []), 1):
        lines.append(f"| {i} | `{o['label']}` | {o['feasible']} | {o['added_minutes']} | {o['reason']} |")
    lines += [
        "",
        "## What the model tried, and what stopped it",
        "",
        "| # | Gate | Tool | Reason |",
        "|---|---|---|---|",
    ]
    for i, e in enumerate(packet["gate_events"], 1):
        lines.append(f"| {i} | {e['what']} | {e['tool']} | {e['reason'].replace('|', '/')} |")
    if packet["decision_card"]:
        c = packet["decision_card"]
        lines += [
            "",
            "## The rider was asked",
            "",
            f"> {c['question']}",
            "",
            f"Option `{c['option']}`, added minutes {c['added_minutes']}, flags {json.dumps(c['flags'])}, "
            f"source {c['source_url']}.",
            "",
            "Rejected: " + "; ".join(f"`{r['label']}` ({r['reason']})" for r in c["rejected"]) + ".",
            "",
            f"Answer: {packet['rider_answer']}",
        ]
    lines += ["", "## What reached the rider", ""]
    if packet["final_plan"]:
        lines.append("```json")
        lines.append(json.dumps(packet["final_plan"], indent=2))
        lines.append("```")
    else:
        lines.append("Nothing: the run ended without a plan.")
    lines += ["", "## Run", "", "```mermaid", sequence_diagram(packet), "```", ""]
    if packet["trace_events"]:
        lines += ["## Trace events", "", "```"]
        lines.extend(f"{e['event']:<30} span={e['span']}" for e in packet["trace_events"])
        lines += ["```", ""]
    c = packet["counts"]
    lines.append(
        f"Counts: hook cancels {c['hook_cancel']}, guides before the tool {c['guide_before_tool']}, "
        f"guides after the model {c['guide_after_model']}, proceeds {c['proceed_after_model']}, "
        f"interrupts {c['interrupts']}, model calls {c['model_calls']}."
    )
    cost = packet.get("cost")
    if cost:
        lines.append(
            f"Cost of this decision: {cost['model_calls']} model call(s), {cost['input_tokens']} input and "
            f"{cost['output_tokens']} output tokens ({cost['total_tokens']} total), {cost['cycles']} event-loop "
            "cycle(s), as reported by the provider through Strands' metrics."
        )
    return "\n".join(lines) + "\n"
