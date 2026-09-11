"""Agent tools.

PLACEHOLDERS (Block A). Each tool returns canned data so the harness, hook, steering, and
structured-output paths can be tested offline. B6 replaces the bodies with the station KB,
the policy engine, and the message drafter. The signatures are the contract.
"""

from __future__ import annotations

from typing import Any

from strands import tool

# Placeholder station set used by the argument validator until kb/ exists (B1).
PLACEHOLDER_STATIONS: frozenset[str] = frozenset({"DELN", "SANL", "EMBR", "ASHB", "ELCE", "RICH", "MONT"})


@tool
def get_station_facts(station: str) -> dict[str, Any]:
    """Look up a BART station's elevators, accessible pathways, and documented outage options.

    Args:
        station: Four-letter BART station abbreviation, for example "DELN".
    """
    return {
        "station": station,
        "elevators": ["PLACEHOLDER"],
        "pathways": ["PLACEHOLDER"],
        "documented_outage_options": [],
        "source": "PLACEHOLDER until kb/ is built (B1)",
    }


@tool
def plan_alternatives(origin: str, destination: str, outage: str) -> dict[str, Any]:
    """List feasible options for a rider trip given one elevator outage, in BART's published order.

    Args:
        origin: Origin station abbreviation.
        destination: Destination station abbreviation.
        outage: The outage description from the BART feed, for example "DELN: Platform - Richmond".
    """
    return {
        "origin": origin,
        "destination": destination,
        "outage": outage,
        "options": [{"option": "backtracking", "feasible": True, "added_minutes": 0, "note": "PLACEHOLDER"}],
    }


@tool
def draft_message(option: str, steps: list[str]) -> str:
    """Draft the plain-language message sent to the rider for a chosen option and its steps.

    Args:
        option: The recommended option name.
        steps: The concrete steps the rider will take.
    """
    joined = " ".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    return f"PLACEHOLDER draft. Option: {option}. Steps: {joined}"


PLACEHOLDER_TOOLS = [get_station_facts, plan_alternatives, draft_message]
