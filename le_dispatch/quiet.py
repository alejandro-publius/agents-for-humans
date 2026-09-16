"""F4: the quiet metric. How often does the agent bother a rider?

Replay a synthetic week: three synthetic riders with saved trips, a
schedule of elevator outages at five-minute resolution, the poller's view
at each departure. For every rider-trip-day the policy engine decides
affectedness; affected trips run through the full agent (F1 gates, F2
interrupt handler) on a compliant scripted model. Everything the rider
would see is logged as an event:

    quiet        nothing affected the trip; the rider heard nothing
    plan_sent    handled in the background, no question asked
    interrupt    the rider was asked (after dark or last train)
    decision     the rider answered (scripted: yes)

results/quiet.json carries interruptions per rider-week, and the weekly
report opens with "N days, X interruptions, Y decisions".
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from .interfaces import FIXTURES, KBSet, PolicyCallable, Trip, keep_the_real_file
from .interrupts import DecisionMemory, Inbox, build_decision_run
from .messages import composed_plan
from .scripted_model import ScriptedModel, plan_call, tool_call

RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "quiet.json"


@dataclass
class ReplayEvent:
    day: int
    rider_id: str
    trip: str
    depart_local: str
    kind: str  # quiet | plan_sent | interrupt | decision
    case_key: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def active_outages(schedule: dict[str, Any], day: int, depart_local: str) -> tuple[str, ...]:
    t = _minutes(depart_local)
    out = []
    for o in schedule["outages"]:
        if o["day"] == day and _minutes(o["from"]) <= t <= _minutes(o["to"]):
            out.append(o["elevator"])
    return tuple(sorted(out))


def compliant_script(decision) -> list[list[dict[str, Any]]]:
    d = decision
    plan = composed_plan(d)
    return [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        plan_call(plan, "p1"),
    ]


def replay_week(
    kb: KBSet,
    policy: PolicyCallable,
    riders: dict[str, Any],
    schedule: dict[str, Any],
    *,
    workdir: str | Path | None = None,
    rider_answers: bool = True,
) -> list[ReplayEvent]:
    """Run the week. Decision memory persists per rider across days, so a
    case the rider already decided never interrupts twice."""
    workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="le-quiet-"))
    dark_from = _minutes(riders.get("after_dark_from", "19:30"))
    last_from = _minutes(riders.get("last_train_from", "23:30"))
    events: list[ReplayEvent] = []
    memories = {r["rider_id"]: DecisionMemory(workdir / f"{r['rider_id']}-decisions.json") for r in riders["riders"]}
    inbox = Inbox(workdir / "inbox.json")
    for day in range(schedule["days"]):
        for rider in riders["riders"]:
            for saved in rider["trips"]:
                if day not in saved.get("days", list(range(7))):
                    continue
                depart = saved["depart_local"]
                t = _minutes(depart)
                trip = Trip(
                    rider_id=rider["rider_id"],
                    origin=saved["origin"],
                    destination=saved["destination"],
                    outages=active_outages(schedule, day, depart),
                    via=tuple(saved.get("via", ())),
                    after_dark=t >= dark_from,
                    last_train=t >= last_from,
                )
                label = f"{trip.origin}>{trip.destination}"
                decision = policy(trip)
                if not decision.affected:
                    events.append(ReplayEvent(day, trip.rider_id, label, depart, "quiet"))
                    continue
                run = build_decision_run(
                    ScriptedModel(compliant_script(decision)),
                    kb,
                    policy,
                    trip,
                    inbox=inbox,
                    memory=memories[trip.rider_id],
                )
                out = run.start()
                detail = {"option": decision.top_option, "kind": decision.kind, "flags": decision.flags}
                if out.state == "pending":
                    events.append(ReplayEvent(day, trip.rider_id, label, depart, "interrupt", trip.case_key, detail))
                    out = run.resume(rider_answers)
                    answered = {"answer": rider_answers}
                    events.append(ReplayEvent(day, trip.rider_id, label, depart, "decision", trip.case_key, answered))
                sent = {**detail, "state": out.state}
                events.append(ReplayEvent(day, trip.rider_id, label, depart, "plan_sent", trip.case_key, sent))
    return events


def quiet_metric(events: list[ReplayEvent], days: int, riders: int) -> dict[str, Any]:
    interruptions = sum(1 for e in events if e.kind == "interrupt")
    decisions = sum(1 for e in events if e.kind == "decision")
    plans = sum(1 for e in events if e.kind == "plan_sent")
    quiet = sum(1 for e in events if e.kind == "quiet")
    rider_weeks = riders * days / 7
    return {
        "days": days,
        "riders": riders,
        "rider_weeks": round(rider_weeks, 3),
        "trips_checked": plans + quiet,
        "quiet_trips": quiet,
        "plans_sent": plans,
        "plans_sent_in_background": plans - interruptions,
        "interruptions": interruptions,
        "decisions": decisions,
        "interrupts_per_rider_week": round(interruptions / rider_weeks, 3) if rider_weeks else None,
        "opening_line": opening_line(days, interruptions, decisions),
    }


def opening_line(days: int, interruptions: int, decisions: int) -> str:
    return f"{days} days, {interruptions} interruptions, {decisions} decisions"


def write_results(
    metric: dict[str, Any],
    events: list[ReplayEvent],
    path: Path = RESULTS_PATH,
    *,
    provenance: str,
    week: str = "synthetic",
    riders: str = "synthetic",
):
    """`week` and `riders` say what the replay ran on: "synthetic" (the fixtures) or "archive" / "real"."""
    note = (
        "Synthetic riders and a synthetic outage week. Rerun on the laptop (make report REPORT_ARGS=--archive ...) "
        "on the archive replay before citing."
        if week == "synthetic"
        else f"The outage week is the archive's ({week}); the riders are {riders}. A number about the riders "
        "stays synthetic until real trips are passed (--riders)."
    )
    doc = {
        "provenance": {
            "run": provenance,
            "claimable": False,
            "week": week,
            "riders": riders,
            "note": note,
        },
        **metric,
        "events": [asdict(e) for e in events],
    }
    if keep_the_real_file(path, this_run_is_real=week != "synthetic"):
        doc["provenance"]["kept"] = f"{path} holds the archive's week; this synthetic replay wrote nothing"
        return doc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def weekly_report(doc: dict[str, Any]) -> str:
    """The weekly quiet report. Its first line is the metric."""
    lines = [doc["opening_line"], ""]
    lines.append(
        f"{doc['riders']} riders, {doc['trips_checked']} trips checked, {doc['quiet_trips']} quiet, "
        f"{doc['plans_sent_in_background']} handled in the background, {doc['interruptions']} asked the rider."
    )
    lines.append(f"Interruptions per rider-week: {doc['interrupts_per_rider_week']}")
    prov = doc.get("provenance", {})
    if prov.get("week"):  # which week and whose riders this is, on the report itself
        lines.append(f"The week: {prov['week']}; the riders: {prov.get('riders', 'synthetic')}.")
    lines.append("")
    for e in doc.get("events", []):
        if e["kind"] in ("interrupt", "decision", "plan_sent"):
            lines.append(f"  day {e['day']} {e['depart_local']} {e['rider_id']:<13} {e['trip']:<10} {e['kind']}")
    return "\n".join(lines)


def schedule_from_rows(rows: list[dict[str, Any]], tz: str = "America/Los_Angeles") -> dict[str, Any]:
    """The archive's public rows (`le_dispatch/dataset_export.to_public_rows`) as the schedule the replay
    takes: day 0 is the local date of the earliest first_seen, every outage is cut at local midnight into
    one segment per day, minutes are floored to the poller's five. The same replay then runs on the real
    week the feed recorded, with whatever riders are given (synthetic here; the laptop may pass real
    trips)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    local = ZoneInfo(tz)

    def parse(ts: str) -> datetime:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(local)

    if not rows:
        raise ValueError("an empty archive")
    spans = [(parse(r["first_seen_utc"]), parse(r["last_seen_utc"]), r["elevator"]) for r in rows]
    day0 = min(first for first, _, _ in spans).date()
    days = max(last for _, last, _ in spans).date().toordinal() - day0.toordinal() + 1
    outages = []
    for first, last, elevator in spans:
        cursor = first
        while cursor <= last:
            day = cursor.date().toordinal() - day0.toordinal()
            end_of_day = datetime.combine(cursor.date(), datetime.max.time(), tzinfo=local).replace(microsecond=0)
            stop = min(last, end_of_day)
            outages.append(
                {
                    "day": day,
                    "elevator": elevator,
                    "from": f"{cursor.hour:02d}:{cursor.minute - cursor.minute % 5:02d}",
                    "to": "23:59" if stop == end_of_day else f"{stop.hour:02d}:{stop.minute:02d}",
                }
            )
            cursor = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time(), tzinfo=local)
    outages.sort(key=lambda o: (o["day"], o["elevator"], o["from"]))
    source = f"the outage archive's rows, {len(rows)} outages, local time {tz}"
    return {"source": source, "days": days, "outages": outages}


def load_fixture_week() -> tuple[dict[str, Any], dict[str, Any]]:
    riders = json.loads((FIXTURES / "riders.json").read_text())
    schedule = json.loads((FIXTURES / "outage_schedule.json").read_text())
    return riders, schedule
