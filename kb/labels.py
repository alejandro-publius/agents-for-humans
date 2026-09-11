"""Deterministic option labels for BART's outage-option texts. Code, not judgment.

Rank order (best first): alternate_elevator, backtracking, transit, mitigation_trip, mitigation_shuttle.

STRICT rules are the mapping specified in the work order and are applied first, in that order.
EXTENDED rules cover phrasings BART uses that the strict rules do not name (for example
"Take the other platform elevator", "Use the ramp", "Continue on train to exit at another
station"). Every labeled option records which tier produced its label, and
``results/kb_label_distribution.json`` reports the distribution under strict rules alone and
with the extension, so the extension is reviewable and removable.
"""

from __future__ import annotations

OPTION_ORDER = ("alternate_elevator", "backtracking", "transit", "mitigation_trip", "mitigation_shuttle")

STRICT: dict[str, tuple[str, ...]] = {
    "alternate_elevator": ("alternative street elevator", "other street elevator", "alternate elevator"),
    "backtracking": ("opposite platform", "go back to", "return to"),
    "transit": (
        "another mode of transportation",
        "ac transit",
        "muni",
        "bus",
        "continue on bart to exit at another station",
    ),
}

EXTENDED: dict[str, tuple[str, ...]] = {
    "alternate_elevator": (
        "other platform elevator",
        "alternative platform elevator",
        "alternative elevator",
        "alternate parking garage elevator",
        "elevator in the bart parking garage",
        "caltrain platform",
        "bart platform 3 elevator",
        "opposite (east plaza) side",
        "platform elevators inside the station",
        "union square market street station elevators",
        "ramp",
        "other side of the station",
        "surface streets",
    ),
    "backtracking": ("take bart to the", "board desired train", "board the desired train"),
    "transit": (
        "continue on train to exit at another station",
        "continue on bart to another station",
        "alternative mode of transportation",
        "station street elevator",
        "walk, roll",
        "walk or roll",
        "drive, walk, or roll",
    ),
}


def _strict_label(text: str) -> str | None:
    t = text.lower()
    if any(k in t for k in STRICT["alternate_elevator"]):
        return "alternate_elevator"
    if any(k in t for k in STRICT["backtracking"]) or ("continue on bart" in t and "exit using" in t):
        return "backtracking"
    if any(k in t for k in STRICT["transit"]):
        return "transit"
    return None


def _extended_label(text: str) -> str | None:
    t = text.lower()
    for label in ("alternate_elevator", "backtracking", "transit"):
        if any(k in t for k in EXTENDED[label]):
            return label
    return None


def label_option(text: str) -> tuple[str, str]:
    """Return (label, rule) where rule is 'strict', 'extended', or 'default'."""
    strict = _strict_label(text)
    if strict:
        return strict, "strict"
    extended = _extended_label(text)
    if extended:
        return extended, "extended"
    return "mitigation_trip", "default"


def strict_only_label(text: str) -> str:
    return _strict_label(text) or "mitigation_trip"
