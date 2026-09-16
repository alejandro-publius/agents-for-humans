"""Decision cards: what a rider sees when the agent pauses for a human decision. Pure code.

A card is built from the policy engine's Decision only: BART's documented option, the minutes the
engine computed, the flags that triggered the pause, the KB source URL, and every rejected option
with its one-line reason. The model never writes a card.
"""

from __future__ import annotations

from typing import Any

from kb.load import station
from policy import Decision

DECISION_FLAGS = ("after_dark", "last_train")


def case_key(station_abbr: str, elevator: str, condition: str) -> str:
    return f"{station_abbr.upper()}|{elevator}|{condition}"


def decision_flags(decision: Decision) -> list[str]:
    """Flags that make this a rider decision rather than an automatic plan."""
    return [f for f in DECISION_FLAGS if decision.flags.get(f) is True]


def build_card(decision: Decision) -> dict[str, Any]:
    record = station(decision.station) or {}
    top = next((o for o in decision.ranked_options if o.option == decision.top_option), None)
    rejected = [
        {"option": o.option, "reason": o.reason or "ranked below the recommended option"}
        for o in decision.ranked_options
        if o.option != decision.top_option
    ]
    return {
        "case_key": case_key(decision.station, decision.elevator, decision.condition),
        "station": decision.station,
        "station_name": record.get("name", decision.station),
        "elevator": decision.elevator,
        "condition": decision.condition,
        "bart_option": (decision.documented_option or {}).get("text"),
        "recommended": decision.top_option,
        "added_minutes": top.added_minutes if top else None,
        "minutes_basis": top.minutes_basis if top else None,
        "flags": decision_flags(decision),
        "source_url": record.get("source_url"),
        "scraped_at": record.get("scraped_at"),
        "rejected_options": rejected,
        "question": (
            "Accept the recommended option, or decline to request a Mitigation Trip from the Station Agent?"
        ),
    }
