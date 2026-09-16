"""Deterministic option labels for BART's outage-option texts. Code, not judgment.

Rank order (best first): alternate_elevator, backtracking, transit, mitigation_trip, mitigation_shuttle.

Every phrase below was decided by the reviewer against the actual KB texts (work order Fri Sept 11;
additions and the 44 remaining defaults Sat Sept 12, 2026). Rules are applied in rank order:
alternate_elevator phrases first, then backtracking, then transit; anything unmatched is
mitigation_trip and is counted as a default in ``results/kb_label_distribution.json``.

``alternate_elevator`` means an alternate accessible path at the same station, including ramps,
lifts and tunnels, not only another elevator car.
"""

from __future__ import annotations

OPTION_ORDER = ("alternate_elevator", "backtracking", "transit", "mitigation_trip", "mitigation_shuttle")

PHRASES: dict[str, tuple[str, ...]] = {
    "alternate_elevator": (
        # work order, Sept 11
        "alternative street elevator",
        "other street elevator",
        "alternate elevator",
        # reviewer additions, Sept 12
        "other platform elevator",
        "other elevator",
        "alternative elevator",
        # same-complex elevators (19TH, WDUB, MLBR, POWL, WARM)
        "alternative platform elevator",
        "alternate parking garage elevator",
        "elevator in the bart parking garage",
        "opposite (east plaza) side",
        "caltrain platform 4",
        "bart platform 3 elevator",
        "union square market street station elevators",
        "platform elevators inside the station",
        # ramps (ASHB, RICH, COLS arena bridge)
        "ramp",
        # same-station surface routes (COLS lift at the other entrance, DALY tunnel to the main entrance)
        "other side of the station",
        "surface streets",
        "drive, walk, or roll",
        "other side of the tunnel",
    ),
    "backtracking": (
        "opposite platform",
        "go back to",
        "return to",
        # MLPT: use the other platform's elevator, ride to Berryessa, board the desired train
        "take bart to the",
    ),
    "transit": (
        "another mode of transportation",
        "ac transit",
        "muni",
        "bus",
        "continue on bart to exit at another station",
        # Sept 12: exiting at the next station (CIVC, EMBR, MONT, POWL, COLM, SSAN)
        "continue on train to exit at another station",
        "continue on bart to another station",
        # Sept 12: EMBR, walk to Montgomery's street elevator
        "montgomery station street elevator",
        # Sept 12: WARM bridge
        "alternative mode of transportation",
    ),
}


def _match(text: str) -> str | None:
    t = text.lower()
    if any(k in t for k in PHRASES["alternate_elevator"]):
        return "alternate_elevator"
    if any(k in t for k in PHRASES["backtracking"]) or ("continue on bart" in t and "exit using" in t):
        return "backtracking"
    if any(k in t for k in PHRASES["transit"]):
        return "transit"
    return None


def label_option(text: str) -> tuple[str, str]:
    """Return (label, rule) where rule is 'phrase' or 'default'."""
    label = _match(text)
    return (label, "phrase") if label else ("mitigation_trip", "default")
