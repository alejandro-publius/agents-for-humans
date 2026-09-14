"""What riders faced, from the agency's own feed: the outage archive summarised as impact numbers.

The quiet report says what the agent did for three riders in a week. This says what the feed said about
the whole system over the archive's span, the numbers a judge asks for when "potential impact" is on the
rubric: how many elevators went out, at how many stations, for how many elevator-hours, the longest, how
many were still open at export, how many happened after dark (an outage in progress at nine in the
evening local time, when the agent asks instead of sending), how many stations lost every elevator the
knowledge base lists for them at the same moment (a station cut off), and how much of the knowledge base
the week touched (elevators in the archive that the cases cover). Everything is computed from the public
rows the dataset export produces (`le_dispatch/dataset_export.py`), so the fixture archive gives fixture
numbers and the real archive gives real ones with the same code. Nothing here is a result until the laptop
runs it on `data/archive/`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .dataset_export import FIXTURE_ARCHIVE, ArchiveAdapter, to_public_rows
from .interfaces import ROOT, KBSet, claimable, data_source, keep_the_real_file, load_cases

RESULTS_PATH = ROOT / "results" / "outage_week.json"
LOCAL = ZoneInfo("America/Los_Angeles")
NIGHT_HOUR = 21  # nine in the evening: the hour the policy's after-dark rule is certainly on


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _local_nights(first: datetime, last: datetime) -> int:
    """How many evenings (nine o'clock local) fell inside the outage."""
    count = 0
    day = first.astimezone(LOCAL).replace(hour=NIGHT_HOUR, minute=0, second=0, microsecond=0)
    if day < first.astimezone(LOCAL):
        day += timedelta(days=1)
    while day <= last.astimezone(LOCAL):
        count += 1
        day += timedelta(days=1)
    return count


def cut_off_stations(rows: list[dict[str, Any]], kb: KBSet) -> list[dict[str, Any]]:
    """Stations where every elevator the knowledge base lists was out at the same moment, with the longest
    such stretch in minutes. An interval sweep per station over the rows' first_seen and last_seen."""
    by_station: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    for r in rows:
        by_station[r["station"]].append((_parse(r["first_seen_utc"]), _parse(r["last_seen_utc"]), r["elevator"]))
    out = []
    for station, intervals in sorted(by_station.items()):
        listed = sorted(e for e in kb.elevators if e.startswith(f"{station}-"))
        if not listed or len(listed) > len({e for _, _, e in intervals}):
            continue  # not every listed elevator appears in the archive for this station
        points = sorted({t for a, b, _ in intervals for t in (a, b)})
        longest = 0
        for a, b in zip(points, points[1:], strict=False):
            out_now = {e for s, t, e in intervals if s <= a and t >= b}
            if set(listed) <= out_now:
                longest += int((b - a).total_seconds() // 60)
        if longest:
            out.append({"station": station, "elevators": listed, "minutes_cut_off": longest})
    return out


def summarise(
    rows: list[dict[str, Any]], kb: KBSet, cases: list[Any] | None = None, *, archive: str = "fixture"
) -> dict[str, Any]:
    """`archive` names what the rows came from: "fixture", or the real archive's file name; the numbers are
    claimable only when the archive is real and the knowledge base and cases are the real exports."""
    if not rows:
        raise ValueError("an empty archive")
    firsts = [_parse(r["first_seen_utc"]) for r in rows]
    lasts = [_parse(r["last_seen_utc"]) for r in rows]
    span_start, span_end = min(firsts), max(lasts)
    span_days = max(1, round((span_end - span_start).total_seconds() / 86400, 1))
    durations = sorted(r["duration_minutes"] for r in rows)
    longest = max(rows, key=lambda r: r["duration_minutes"])
    nights = sum(_local_nights(_parse(r["first_seen_utc"]), _parse(r["last_seen_utc"])) for r in rows)
    covered = {c.elevator for c in (cases or load_cases())}
    in_kb = sorted({r["elevator"] for r in rows if r["elevator"] in kb.elevators})
    in_cases = sorted({r["elevator"] for r in rows if r["elevator"] in covered})
    cut = cut_off_stations(rows, kb)
    return {
        "provenance": {
            "run": "the outage archive's public rows summarised (le_dispatch/impact.py); the same code on the fixture "
            "archive and on the real one",
            "claimable": claimable() and archive != "fixture",
            "archive": archive,
            "source": data_source(),
            "note": "Impact numbers about the feed, never about the agent; fixture numbers until the laptop runs "
            "make impact IMPACT_ARGS=--archive on data/archive/.",
        },
        "span": {
            "start_utc": min(r["first_seen_utc"] for r in rows),
            "end_utc": max(r["last_seen_utc"] for r in rows),
            "days": span_days,
        },
        "outages": len(rows),
        "stations": len({r["station"] for r in rows}),
        "elevators": len({r["elevator"] for r in rows}),
        "elevator_hours": round(sum(durations) / 60, 1),
        "median_minutes": durations[len(durations) // 2],
        "longest": {
            "station": longest["station"],
            "elevator": longest["elevator"],
            "minutes": longest["duration_minutes"],
        },
        "open_at_export": sum(1 for r in rows if r["status"] == "open"),
        "evenings_with_an_outage_in_progress": nights,
        "elevators_in_knowledge_base": len(in_kb),
        "elevators_with_a_case": len(in_cases),
        "stations_cut_off": cut,
        "stations_cut_off_count": len(cut),
    }


def render(doc: dict[str, Any]) -> str:
    longest = doc["longest"]
    hours = longest["minutes"] / 60
    lines = [
        f"over {doc['span']['days']} days ({doc['span']['start_utc']} to {doc['span']['end_utc']}): "
        f"{doc['outages']} elevator outages at {doc['stations']} stations, {doc['elevators']} elevators, "
        f"{doc['elevator_hours']} elevator-hours out",
        f"  median {doc['median_minutes']} minutes; longest {hours:.1f} hours "
        f"({longest['station']} {longest['elevator']}); {doc['open_at_export']} still open at export",
        f"  {doc['evenings_with_an_outage_in_progress']} evening(s) with an outage in progress at nine o'clock local "
        "(when the agent asks the rider instead of sending)",
        f"  {doc['elevators_in_knowledge_base']} of the {doc['elevators']} elevators are in the knowledge base, "
        f"{doc['elevators_with_a_case']} have a labelled case",
    ]
    if doc["stations_cut_off"]:
        cut = ", ".join(
            f"{c['station']} ({c['minutes_cut_off']} min, {len(c['elevators'])} "
            f"elevator{'s' if len(c['elevators']) != 1 else ''} listed)"
            for c in doc["stations_cut_off"]
        )
        lines.append(f"  stations with every listed elevator out at once: {cut}")
    else:
        lines.append("  no station had every listed elevator out at once")
    return "\n".join(lines)


def run(archive: Path, kb: KBSet, query: str | None = None, cases: list[Any] | None = None) -> dict[str, Any]:
    adapter = ArchiveAdapter(archive, query) if query else ArchiveAdapter(archive)
    name = "fixture" if archive.resolve() == FIXTURE_ARCHIVE.resolve() else archive.name
    return summarise(to_public_rows(adapter.rows()), kb, cases, archive=name)


def write(doc: dict[str, Any], path: Path = RESULTS_PATH) -> bool:
    """Write the file; False, and nothing written, when `path` holds a real run and this one is the fixture's."""
    if keep_the_real_file(path, this_run_is_real=doc["provenance"]["archive"] != "fixture"):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return True
