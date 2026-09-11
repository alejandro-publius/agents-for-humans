"""Outage parser. The model proposes a structured parse of BART's free-text fragment; code
validates it against the KB and resolves which KB elevator is out.

Fragment shape (documented sample): ``"DELN: Platform - Richmond"``. After the colon, the first
word is the elevator's level; after the dash is either a second level (``"Street - Concourse"``)
or a platform/direction label (``"Richmond"``). Nothing here decides whether a trip is affected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from strands import Agent
from strands.types.exceptions import StructuredOutputException

from kb.load import load_stations

LEVELS = frozenset(
    {"street", "concourse", "platform", "plaza", "garage", "tunnel", "bridge", "walkway", "mezzanine"}
)

# What each parsed level word can mean in terms of the KB's elevator kinds (from BART's headings).
LEVEL_TO_KINDS = {
    "street": {"street"},
    "concourse": {"street", "station"},
    "platform": {"platform", "station"},
    "plaza": {"street", "caltrain"},
    "garage": {"garage"},
    "tunnel": {"tunnel"},
    "bridge": {"bridge"},
    "walkway": {"street", "bridge"},
}


class OutageParse(BaseModel):
    """The model's proposal. Every field is checked by code before use."""

    station_abbr: str = Field(description="Four-character BART station code exactly as written, e.g. DELN.")
    level_from: str = Field(
        description="The first word after the colon, lowercased: street, concourse, platform, plaza, garage, "
        "tunnel, bridge, or walkway."
    )
    level_to: str | None = Field(
        default=None,
        description="The word after the dash if it is also a level "
        "(e.g. 'Street - Concourse' -> 'concourse'); otherwise null.",
    )
    platform_label: str | None = Field(
        default=None,
        description="The text after the dash when it is a direction or location label rather than a level "
        "(e.g. 'Richmond', 'SFO/Millbrae/Daly City'); otherwise null.",
    )


PARSER_SYSTEM_PROMPT = """\
You turn one BART elevator outage fragment into fields. Copy the station code exactly. Do not guess
levels that are not written. Finish by calling the OutageParse tool exactly once.
"""

FRAGMENT_RE = re.compile(r"^\s*([A-Za-z0-9]{4}):\s*(.+?)\s*-\s*(.+?)\s*$")


def parse_outage_regex(fragment: str) -> OutageParse | None:
    """Deterministic baseline for the documented ``ABBR: Level - Label`` shape."""
    m = FRAGMENT_RE.match(fragment)
    if not m:
        return None
    abbr, first, second = m.group(1).upper(), m.group(2).strip(), m.group(3).strip()
    if second.lower() in LEVELS:
        return OutageParse(station_abbr=abbr, level_from=first.lower(), level_to=second.lower())
    return OutageParse(station_abbr=abbr, level_from=first.lower(), platform_label=second)


def parse_outage_with_model(fragment: str, model: Any) -> tuple[OutageParse | None, int]:
    """Ask the model for a structured parse. Returns (proposal or None, model calls made)."""
    agent = Agent(
        model=model,
        tools=[],
        system_prompt=PARSER_SYSTEM_PROMPT,
        structured_output_model=OutageParse,
        callback_handler=None,
    )
    try:
        result = agent(f"Parse this BART elevator outage fragment: {fragment}")
    except StructuredOutputException:
        # The model never called the OutageParse tool, even after the forced follow-up. No proposal.
        return None, len(getattr(model, "calls", [])) or 1
    proposal = result.structured_output if isinstance(result.structured_output, OutageParse) else None
    return proposal, len(getattr(model, "calls", [])) or 1


@dataclass
class ValidatedOutage:
    raw: str
    station_abbr: str | None
    level_from: str | None
    level_to: str | None
    platform_label: str | None
    kb_elevator: str | None
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.station_abbr is not None and self.kb_elevator is not None

    def as_label(self) -> dict[str, Any]:
        return {
            "station_abbr": self.station_abbr,
            "level_from": self.level_from,
            "level_to": self.level_to,
            "platform_label": self.platform_label,
            "kb_elevator": self.kb_elevator,
        }


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def resolve_elevator(station_record: dict[str, Any], level_from: str | None, label: str | None) -> str | None:
    """Pick the unique KB elevator the fragment names, or None when it is ambiguous. Pure code."""
    elevators = station_record["elevators"]
    names = [e["name"] for e in elevators]
    kinds = {e["name"]: e["kind"] for e in elevators}
    if label:
        tokens = [t for t in _norm(label).split() if len(t) >= 3]
        scored = [(sum(t in _norm(n).split() for t in tokens), n) for n in names]
        best = max((s for s, _ in scored), default=0)
        if best > 0:
            matches = [n for s, n in scored if s == best]
            if len(matches) == 1:
                return matches[0]
            wanted = LEVEL_TO_KINDS.get(level_from or "", set())
            narrowed = [n for n in matches if kinds[n] in wanted]
            return narrowed[0] if len(narrowed) == 1 else None
    wanted = LEVEL_TO_KINDS.get(level_from or "", set())
    by_kind = [n for n in names if kinds[n] in wanted]
    if len(by_kind) == 1:
        return by_kind[0]
    if len(names) == 1:
        return names[0]
    return None


def validate_against_kb(proposal: OutageParse | None, raw: str) -> ValidatedOutage:
    """Code decides: unknown stations are nulled, level words are checked, the elevator is resolved."""
    if proposal is None:
        return ValidatedOutage(raw, None, None, None, None, None, ["no parse proposed"])
    stations = load_stations()
    problems: list[str] = []

    abbr: str | None = proposal.station_abbr.upper().strip()
    if abbr not in stations:
        problems.append(f"station {abbr!r} is not in the KB")
        abbr = None

    level_from: str | None = proposal.level_from.lower().strip()
    if level_from not in LEVELS:
        problems.append(f"level_from {level_from!r} is not a known level word")
        level_from = None

    level_to: str | None = proposal.level_to.lower().strip() if proposal.level_to else None
    if level_to is not None and level_to not in LEVELS:
        problems.append(f"level_to {level_to!r} is not a known level word")
        level_to = None

    label = proposal.platform_label.strip() if proposal.platform_label else None
    kb_elevator = resolve_elevator(stations[abbr], level_from, label) if abbr else None
    if abbr and kb_elevator is None:
        problems.append("no unique KB elevator matches the fragment")
    return ValidatedOutage(raw, abbr, level_from, level_to, label, kb_elevator, problems)


def parse_and_validate(fragment: str, model: Any | None = None) -> ValidatedOutage:
    """Model path when a model is given, regex baseline otherwise; validation is identical."""
    if model is not None:
        proposal = parse_outage_with_model(fragment, model)[0]
    else:
        proposal = parse_outage_regex(fragment)
    return validate_against_kb(proposal, fragment)
