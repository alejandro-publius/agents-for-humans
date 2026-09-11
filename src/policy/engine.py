"""Trip matcher and policy engine. Pure code. Inputs: a rider trip and one validated outage.

What this decides (never the model): whether the outage is on the rider's path and in which
condition (cant_enter at the origin, cant_exit at the destination, transfer), which KB option
BART documents for that elevator and condition, the feasible options ranked in BART's order,
the minutes each option adds where a schedule exists, and the after-dark and last-train flags.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from bart import BartClient
from kb.labels import OPTION_ORDER
from kb.load import load_stations
from policy.schedule import last_train_flag, leg_info, round_trip_minutes
from policy.sun import is_after_dark

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
ACCESS_KINDS = {"street", "station"}
ENTRANCE_KINDS = {"garage", "lift", "bridge", "tunnel", "caltrain", "connector", "other"}
WALK_MPH = 3.0  # assumption for converting BART's stated distances into minutes


@dataclass(frozen=True)
class Trip:
    origin: str
    dest: str
    days: tuple[str, ...] = WEEKDAYS
    window: tuple[str, str] = ("00:00", "23:59")
    needs: frozenset[str] = frozenset({"elevator"})
    rider_id: str = "demo"


@dataclass(frozen=True)
class Outage:
    station_abbr: str
    kb_elevator: str
    raw: str = ""


@dataclass
class RankedOption:
    option: str
    rank: int
    source: str
    text: str
    feasible: bool
    reason: str | None = None
    added_minutes: int | None = None
    minutes_basis: str | None = None


@dataclass
class Decision:
    affected: bool | None
    condition: str
    station: str
    elevator: str
    documented_option: dict[str, Any] | None
    ranked_options: list[RankedOption]
    top_option: str | None
    flags: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(text: str) -> set[str]:
    return {t for t in re.sub(r"[^A-Z0-9]+", " ", text.upper()).split() if len(t) >= 3}


def _direction_words(elevator_name: str) -> set[str]:
    m = re.search(r"\(([^)]*)\)", elevator_name)
    return _tokens(m.group(1)) if m else set()


def platform_serves_direction(elevator_name: str, head_station: str) -> bool | None:
    """True/False when the heading names directions; None when it names none."""
    words = _direction_words(elevator_name)
    if not words or not any(w in words for w in ("DIRECTION", "DIRECTIONS", "DESTINATIONS")):
        return None
    if "ALL" in words and "DESTINATIONS" in words:
        return True
    return bool(_tokens(head_station) & words)


def _elevator(station_record: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((e for e in station_record["elevators"] if e["name"] == name), None)


def _option_for(elevator: dict[str, Any], situation_prefix: str) -> dict[str, Any] | None:
    return next((o for o in elevator["outage_options"] if o["situation"].startswith(situation_prefix)), None)


def _station_named_in(text: str, stations: dict[str, dict[str, Any]], exclude: str) -> str | None:
    """The KB station whose name appears in BART's option text (the backtrack station)."""
    upper = text.upper()
    best = None
    for abbr, s in stations.items():
        if abbr == exclude:
            continue
        for candidate in (s["name"], s["page_name"]):
            if candidate and candidate.upper() in upper:
                if best is None or len(candidate) > len(best[1]):
                    best = (abbr, candidate)
    return best[0] if best else None


def _distance_minutes(text: str) -> tuple[int | None, str | None]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*miles?", text, flags=re.IGNORECASE)
    if not m:
        return None, None
    miles = float(m.group(1))
    return round(miles / WALK_MPH * 60), f"{miles} miles stated by BART at {WALK_MPH} mph (assumption)"


def _window_flags(trip: Trip, when: datetime) -> dict[str, Any]:
    day = WEEKDAYS[when.weekday()]
    start, end = trip.window
    hhmm = when.strftime("%H:%M")
    return {
        "day_matches": day in trip.days,
        "in_window_now": start <= hhmm <= end,
        "checked_at": when.isoformat(),
    }


def assess(trip: Trip, outage: Outage, when: datetime, client: BartClient | None = None) -> Decision:
    """Decide. ``when`` must be an aware datetime."""
    client = client or BartClient()
    stations = load_stations()
    origin, dest, station = trip.origin.upper(), trip.dest.upper(), outage.station_abbr.upper()
    notes: list[str] = []
    flags: dict[str, Any] = _window_flags(trip, when)
    flags["after_dark"] = is_after_dark(when)

    record = stations.get(station)
    if record is None:
        return _refuse("unknown_station", station, outage.kb_elevator, flags, "station not in KB")
    elevator = _elevator(record, outage.kb_elevator)
    if elevator is None:
        return _refuse("unknown_elevator", station, outage.kb_elevator, flags, "elevator not in KB")

    if station == origin:
        situation = "cant_enter"  # boarding
    elif station == dest:
        situation = "cant_exit"  # exiting
    else:
        reason = "station is not on this trip"
        return _refuse("not_on_trip", station, elevator["name"], flags, reason, affected=False)

    legs = leg_info(client, origin, dest)
    flags["direction_source"] = legs.source if legs else "unknown: no schedule data for this trip"
    head = legs.head_stations[0] if legs and legs.head_stations else None

    affected: bool | None
    if elevator["kind"] == "platform":
        serves = platform_serves_direction(elevator["name"], head) if head else None
        if serves is None and head is not None:
            serves = True  # heading names no direction: the station's platform elevator(s) serve every train
            notes.append("elevator heading names no direction; treated as serving this trip")
        if serves is None:
            reason = "cannot tell which platform this trip uses without schedule data"
            return _refuse("unknown_direction", station, elevator["name"], flags, reason, notes=notes)
        if not serves:
            reason = f"this trip's train ({head}) does not use that platform elevator"
            return _refuse(
                "other_direction", station, elevator["name"], flags, reason, affected=False, notes=notes
            )
        affected = True
    elif elevator["kind"] in ACCESS_KINDS:
        affected = True
    else:
        affected = None
        notes.append(f"{elevator['kind']} elevator: affects the trip only if the rider uses that entrance")

    return _decide(trip, record, elevator, situation, affected, when, client, flags, notes)


def assess_condition(
    trip: Trip,
    station_abbr: str,
    elevator_name: str,
    situation: str,
    when: datetime,
    client: BartClient | None = None,
) -> Decision:
    """Decide for a condition given by the caller (used by the policy-agreement eval, where every
    (station, elevator, condition) triple from the KB is a case). Path and direction matching are
    skipped; option ranking, minutes, and flags are identical to ``assess``."""
    client = client or BartClient()
    record = load_stations().get(station_abbr.upper())
    flags: dict[str, Any] = _window_flags(trip, when)
    flags["after_dark"] = is_after_dark(when)
    flags["direction_source"] = "condition given by caller"
    if record is None:
        return _refuse("unknown_station", station_abbr.upper(), elevator_name, flags, "station not in KB")
    elevator = _elevator(record, elevator_name)
    if elevator is None:
        return _refuse("unknown_elevator", station_abbr.upper(), elevator_name, flags, "elevator not in KB")
    return _decide(trip, record, elevator, situation, True, when, client, flags, [])


def _decide(trip, record, elevator, situation, affected, when, client, flags, notes) -> Decision:
    station = record["abbr"]
    documented = _option_for(elevator, situation)
    ranked = _rank_options(
        trip, record, documented, station, trip.origin, trip.dest, when, client, flags, notes
    )
    top = next((o.option for o in ranked if o.feasible), None)
    return Decision(affected, situation, station, elevator["name"], documented, ranked, top, flags, notes)


def _refuse(condition, station, elevator, flags, reason, *, affected=None, notes=None) -> Decision:
    return Decision(affected, condition, station, elevator, None, [], None, flags, [*(notes or []), reason])


def _rank_options(trip, record, documented, station, origin, dest, when, client, flags, notes):
    stations = load_stations()
    last_train, last_basis = last_train_flag(client, origin, dest, when)
    flags["last_train"] = last_train
    flags["last_train_basis"] = last_basis
    options: list[RankedOption] = []

    if documented is not None:
        label = documented["option_label"]
        feasible, reason = True, None
        minutes, basis = None, None
        if label == "alternate_elevator" and "larger_elevator" in trip.needs:
            feasible, reason = False, "rider needs a larger elevator; elevator dimensions are not in the KB"
        if label == "backtracking":
            if last_train:
                feasible, reason = False, "no later train to return on (last train)"
            via = _station_named_in(documented["text"], stations, exclude=station)
            if via:
                minutes, basis = round_trip_minutes(client, station, via)
            else:
                basis = "not computed: BART's text names no backtrack station"
        elif label == "transit":
            if "no_bus" in trip.needs:
                feasible, reason = False, "rider cannot use buses"
            basis = "not computed: no transit schedule data"
        elif label == "alternate_elevator":
            minutes, basis = _distance_minutes(documented["text"])
            if minutes is None:
                minutes, basis = 0, "same station, no distance stated"
        options.append(
            RankedOption(
                label,
                OPTION_ORDER.index(label),
                "BART documented option for this elevator",
                documented["text"],
                feasible,
                reason,
                minutes,
                basis,
            )
        )
    else:
        notes.append("BART documents no option for this elevator and condition")

    documented_label = documented["option_label"] if documented else None
    no_bus = (False, "rider cannot use buses") if "no_bus" in trip.needs else (True, None)
    van_text = record["outage_intro"] or "Ask the Station Agent to arrange an accessible van."
    generic = {
        "transit": ("Take a bus or other transit to the nearest station with working elevators.", no_bus),
        "mitigation_trip": (van_text, (True, None)),
        "mitigation_shuttle": ("Mitigation Shuttle (order unverified; see kb/policy.json).", (True, None)),
    }
    for label, (text, (feasible, reason)) in generic.items():
        if label == documented_label:
            continue
        rank = OPTION_ORDER.index(label)
        options.append(
            RankedOption(label, rank, "generic fallback", text, feasible, reason, None, "not computed")
        )
    if flags.get("after_dark"):
        notes.append("after dark: BART lists it as a Mitigation Trip justification (order unverified)")
        if "no_after_dark" in trip.needs:
            # Rider preference: after dark, the Station Agent's accessible van outranks riding or rolling
            # elsewhere. Rank comes from the preference, not from BART's order; the note says so.
            for o in options:
                if o.option in ("backtracking", "transit", "alternate_elevator") and o.feasible:
                    o.feasible = False
                    o.reason = "rider does not travel after dark; Mitigation Trip preferred"
            notes.append("rider preference: never after dark; Mitigation Trip ranked first")
    options.sort(key=lambda o: o.rank)
    return options
