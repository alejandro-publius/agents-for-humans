"""Station-code scrub for plan text. Pure code.

Anything that looks like a BART station code (four upper-case letters or digits) must be a station
in the KB or a word BART itself uses in its elevator headings and option texts (CITY, SIDE, EXIT...).
Any other such token is treated as a hallucinated station and the plan text is replaced by BART's
documented option text, so a made-up station never reaches the rider.
"""

from __future__ import annotations

import re
from functools import lru_cache

from kb.load import load_stations

CODE_RE = re.compile(r"\b[A-Z0-9]{4}\b")
EXTRA_ALLOWED = frozenset({"BART", "MUNI", "SFMTA", "AC", "SFO", "ADA", "LAVTA", "WHEELS"})


@lru_cache(maxsize=1)
def allowed_codes() -> frozenset[str]:
    """KB station codes plus every 4-character upper-case token BART uses in its own texts."""
    tokens = set(EXTRA_ALLOWED)
    for abbr, s in load_stations().items():
        tokens.add(abbr)
        texts = [s["name"], s["page_name"], s["outage_intro"]]
        texts += [e["name"] for e in s["elevators"]]
        texts += [o["text"] for o in s["documented_outage_options"]]
        for text in texts:
            tokens.update(CODE_RE.findall((text or "").upper()))
    return frozenset(tokens)


def unknown_station_codes(*texts: str | None) -> list[str]:
    """Tokens that look like station codes but are not known. Order preserved, unique."""
    allowed = allowed_codes()
    found: list[str] = []
    for text in texts:
        for token in CODE_RE.findall(text or ""):
            if token not in allowed and not token.isdigit() and token not in found:
                found.append(token)
    return found
