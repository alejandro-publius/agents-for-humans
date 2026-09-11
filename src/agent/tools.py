"""Agent tools. Each one is a thin, code-only window onto the KB or the policy engine.

The model chooses when to call them and how to phrase the rider's message. It cannot invent a
station or elevator (the hook cancels those calls), cannot compute minutes (plan_alternatives
returns them from the schedule), and cannot decide whether a trip is affected (also
plan_alternatives, from the policy engine).
"""

from __future__ import annotations

import json
from datetime import datetime

from strands import tool

from bart import BartClient
from kb.load import load_stations, station
from policy import Outage, Trip, assess
from policy.sun import PACIFIC

# Kept for the harness suites that still reference it; real validation uses the KB (B6).
PLACEHOLDER_STATIONS: frozenset[str] = frozenset(load_stations())


@tool
def get_station_facts(station_abbr: str) -> str:
    """Look up one BART station's elevators, their documented outage options, and provenance.

    Args:
        station_abbr: Four-letter BART station abbreviation, for example "DELN".
    """
    record = station(station_abbr)
    if record is None:
        return json.dumps({"error": f"{station_abbr} is not in the knowledge base"})
    return json.dumps(
        {
            "abbr": record["abbr"],
            "name": record["name"],
            "elevators": [
                {
                    "name": e["name"],
                    "kind": e["kind"],
                    "enter_option": e["enter_option"],
                    "exit_option": e["exit_option"],
                    "documented_options": [
                        {"situation": o["situation"], "text": o["text"], "label": o["option_label"]}
                        for o in e["outage_options"]
                        if o["situation"] != "note"
                    ],
                }
                for e in record["elevators"]
            ],
            "pathways_status": record["pathways_status"],
            "source_url": record["source_url"],
            "scraped_at": record["scraped_at"],
        }
    )


@tool
def plan_alternatives(
    origin: str, destination: str, outage_station: str, outage_elevator: str, when_iso: str | None = None
) -> str:
    """Run the policy engine for one rider trip and one outage. Returns whether the trip is
    affected, the condition, BART's documented option, the ranked feasible options in BART's
    order with computed minutes, and the after-dark and last-train flags. Code decides all of it.

    Args:
        origin: Origin station abbreviation.
        destination: Destination station abbreviation.
        outage_station: Station abbreviation of the outage.
        outage_elevator: The elevator name exactly as the knowledge base lists it.
        when_iso: Optional ISO-8601 local time to evaluate at; defaults to now.
    """
    when = datetime.fromisoformat(when_iso) if when_iso else datetime.now(PACIFIC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=PACIFIC)
    trip = Trip(origin=origin, dest=destination)
    decision = assess(trip, Outage(outage_station, outage_elevator), when, BartClient())
    return json.dumps(decision.as_dict(), default=str)


@tool
def draft_message(
    option: str, station_abbr: str, elevator: str, steps: list[str], added_minutes: int | None = None
) -> str:
    """Draft the rider's message for the chosen option. The steering handler rejects any option
    that is not BART's first feasible option for this outage.

    Args:
        option: One of alternate_elevator, backtracking, transit, mitigation_trip, mitigation_shuttle.
        station_abbr: The outage station abbreviation.
        elevator: The elevator name exactly as the knowledge base lists it.
        steps: Concrete steps for the rider, in order, in plain language.
        added_minutes: Extra minutes as returned by plan_alternatives; never estimated.
    """
    record = station(station_abbr)
    name = record["name"] if record else station_abbr
    lines = [f"{name}: {elevator.lower()} is out of service."]
    lines.append(f"Recommended option: {option.replace('_', ' ')}.")
    lines += [f"{i + 1}. {step}" for i, step in enumerate(steps)]
    if added_minutes is not None:
        lines.append(f"Adds about {added_minutes} minutes.")
    draft = {"option": option, "message": " ".join(lines), "steps": steps, "added_minutes": added_minutes}
    return json.dumps(draft)


AGENT_TOOLS = [get_station_facts, plan_alternatives, draft_message]
PLACEHOLDER_TOOLS = AGENT_TOOLS  # name kept for the Block A harness
