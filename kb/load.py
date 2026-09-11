"""Read access to the station knowledge base. Cached; pure code."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

STATIONS_DIR = Path(__file__).resolve().parent / "stations"


@lru_cache(maxsize=1)
def load_stations() -> dict[str, dict[str, Any]]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(STATIONS_DIR.glob("*.json"))}


def known_abbrs() -> frozenset[str]:
    return frozenset(load_stations())


def station(abbr: str) -> dict[str, Any] | None:
    return load_stations().get(abbr.upper().strip())


def elevator_names(abbr: str) -> list[str]:
    s = station(abbr)
    return [e["name"] for e in s["elevators"]] if s else []
