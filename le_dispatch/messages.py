"""Approved rider messages: the rider never receives a sentence the model wrote alone.

Code composes the outbound sentences from the policy decision and BART's
own option text (the KB row's wording), in a few phrasings. The model's
job on the message is to pick one; the plan gate accepts a message only
if it equals an approved sentence (whitespace and trailing punctuation
normalized). Anything else, including text injected through the outage
feed or a station page, is discarded and the model retries with the list.

If the model never produces an approved plan within the turn cap, code
composes the whole plan (`composed_plan`) so the rider is not left
without one; the evidence packet records that the message was composed
by code.
"""

from __future__ import annotations

import re
from typing import Any

from .interfaces import PolicyDecision

LABEL_WORDS_PLAIN = {
    "alternate_elevator": "the alternate elevator route at the same station",
    "backtracking": "backtracking one stop and returning",
    "transit": "the transit connection BART lists",
    "mitigation_trip": "the mitigation trip BART arranges",
    "mitigation_shuttle": "the mitigation shuttle BART arranges",
}

# where the outage bites, in the rider's terms (the policy decision's kind)
KIND_WORDS = {
    "cannot_enter": "at your starting station",
    "cannot_exit": "at your destination",
    "transfer": "at your transfer station",
}

_WS = re.compile(r"\s+")


_TRAIL = re.compile(r"[\s.!]+$")


def normalize(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return _TRAIL.sub("", _WS.sub(" ", text).strip())


def _option_text(decision: PolicyDecision) -> str:
    for o in decision.ranked:
        if o.label == decision.top_option:
            return normalize(o.reason)
    return ""


def _minutes_clause(decision: PolicyDecision) -> str:
    minutes = decision.minutes_for(decision.top_option)
    if minutes is None:
        return ""
    if minutes == 0:
        return "No added time"
    return f"About {minutes} minutes more"


def approved_messages(decision: PolicyDecision) -> list[str]:
    """The sentences the rider may receive for this decision, code-composed.
    Deterministic order; the first (short) is the default the fallback uses."""
    if not decision.affected or not decision.top_option:
        return []
    st, ev = decision.spoken_station, decision.elevator  # the station name when the KB has one: a screen
    words = LABEL_WORDS_PLAIN.get(decision.top_option, decision.top_option)  # reader spells a code letter by letter
    text = _option_text(decision)
    minutes = _minutes_clause(decision)
    where = KIND_WORDS.get(decision.kind or "", "")
    out = f"is out {where}" if where else "is out"  # "is out at your destination"
    tail = f" {minutes}." if minutes else ""
    body = f" {text}." if text else ""
    short_tail = f"; {minutes[0].lower() + minutes[1:]}." if minutes else "."
    return [
        # short first: fits a notification and a screen reader; the card carries the detail
        f"{st} elevator {ev} {out}. Use {words}{short_tail}",
        f"{st} elevator {ev} {out}. BART's option is {words}.{body}{tail}",
        f"Heads up for {st}: elevator {ev} {out}. Use {words}.{body}{tail}",
        f"Elevator {ev} at {st} is out of service {where}. BART's published option is {words}.{body}{tail}".replace(
            "  ", " "
        ),
    ]


def hold_messages(decision: PolicyDecision) -> list[str]:
    """Sentences for a plan kept on file after the rider declined."""
    if not decision.affected or not decision.top_option:
        return []
    st, ev = decision.spoken_station, decision.elevator
    words = LABEL_WORDS_PLAIN.get(decision.top_option, decision.top_option)
    return [
        f"Your plan for {st} is on file at your request: elevator {ev} is out and BART's option is {words}. "
        f"Nothing was sent.",
        f"Kept on file, not sent: {st} elevator {ev} is out; BART's option is {words}.",
    ]


def is_approved(message: Any, decision: PolicyDecision, status: str = "send") -> bool:
    candidates = hold_messages(decision) if status == "hold" else approved_messages(decision)
    return normalize(message) in {normalize(c) for c in candidates}


def approval_hint(decision: PolicyDecision, status: str = "send") -> str:
    candidates = hold_messages(decision) if status == "hold" else approved_messages(decision)
    quoted = " | ".join(f'"{c}"' for c in candidates)
    return f"rider_message must be one of the approved sentences, verbatim: {quoted}"


def composed_plan(decision: PolicyDecision, status: str = "send") -> dict[str, Any]:
    """The whole plan from code, for delivery when the model never converges."""
    messages = hold_messages(decision) if status == "hold" else approved_messages(decision)
    return {
        "station": decision.station,
        "elevator": decision.elevator,
        "option": decision.top_option,
        "added_minutes": decision.minutes_for(decision.top_option),
        "rider_message": messages[0] if messages else "",
        "status": status,
    }
