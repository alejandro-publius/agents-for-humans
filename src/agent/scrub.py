"""Station-code scrub for plan text. Pure code.

Anything that looks like a BART station code (four upper-case letters or digits) must be a station
in the KB or a token BART itself writes in upper case in its elevator headings and option texts
(CITY, SIDE, EXIT...). Any other such token is treated as a hallucinated station and the plan text
is replaced by BART's documented option text, so a made-up station never reaches the rider.

The allowlist is harvested from BART's text *as written*. Upper-casing the source first would
allowlist every ordinary four-letter word BART happens to use in lower-case prose (PARK, HILL,
MAIN, WALK, ...), and those are exactly the plausible codes a model is most likely to invent. The
detector only ever reads upper-case tokens out of a plan, so the allowlist is built the same way.
"""

from __future__ import annotations

import re
from functools import lru_cache

from kb.load import load_stations

CODE_RE = re.compile(r"\b[A-Z0-9]{4}\b")
EXTRA_ALLOWED = frozenset({"BART", "MUNI", "SFMTA", "AC", "SFO", "ADA", "LAVTA", "WHEELS"})


@lru_cache(maxsize=1)
def allowed_codes() -> frozenset[str]:
    """KB station codes plus every 4-character token BART itself writes in upper case."""
    tokens = set(EXTRA_ALLOWED)
    for abbr, s in load_stations().items():
        tokens.add(abbr)
        texts = [s["name"], s["page_name"], s["outage_intro"]]
        texts += [e["name"] for e in s["elevators"]]
        texts += [o["text"] for o in s["documented_outage_options"]]
        for text in texts:
            tokens.update(CODE_RE.findall(text or ""))
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


MINUTES_RE = re.compile(r"(\d+)\s*(?:-|\s)?\s*(?:min\b|mins\b|minute)", re.IGNORECASE)


def unsupported_minutes(computed: int | None, documented: str | None, *texts: str | None) -> list[int]:
    """Minute figures in plan prose that neither the policy engine nor BART's own text supports.

    The structured ``added_minutes`` field is always overwritten from the policy engine, but the
    message the rider reads is free text: a model can write "it adds 1001 minutes" there and the
    field correction never touches it. A figure is accepted only when it equals the computed value
    or appears in BART's documented option text (riders should still see BART's own numbers).
    Order preserved, unique.
    """
    supported = {int(m) for m in MINUTES_RE.findall(documented or "")}
    if computed is not None:
        supported.add(int(computed))
    found: list[int] = []
    for text in texts:
        for raw in MINUTES_RE.findall(text or ""):
            value = int(raw)
            if value not in supported and value not in found:
                found.append(value)
    return found
