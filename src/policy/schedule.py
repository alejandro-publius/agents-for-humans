"""Schedule arithmetic from BART sched.aspx responses (fixtures offline). Pure code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bart import BartClient, BartUnavailable
from bart import Trip as SchedTrip


@dataclass(frozen=True)
class LegInfo:
    head_stations: tuple[str, ...]  # train head station per leg, e.g. ("Daly City",)
    transfer_stations: tuple[str, ...]  # placeholder: sched legs do not name transfer abbrs offline
    source: str


def leg_info(client: BartClient, origin: str, dest: str) -> LegInfo | None:
    """Head stations for the rider's legs, from the schedule. None when no data is available."""
    try:
        trips = client.trips(origin, dest)
    except (BartUnavailable, FileNotFoundError, KeyError):
        return None
    if not trips:
        return None
    first = trips[0]
    return LegInfo(
        head_stations=first.train_head_stations,
        transfer_stations=(),
        source="live schedule" if client.live else f"schedule fixture depart_{origin}_{dest}",
    )


def _parse_clock(text: str) -> int | None:
    """'9:57 AM' -> minutes since midnight."""
    try:
        parsed = datetime.strptime(text.strip(), "%I:%M %p")
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def typical_wait_minutes(trips: list[SchedTrip]) -> int | None:
    """Half the median gap between consecutive departures (the expected wait for a random arrival)."""
    times = sorted(t for t in (_parse_clock(x.orig_time) for x in trips) if t is not None)
    gaps = [b - a for a, b in zip(times, times[1:], strict=False) if b > a]
    if not gaps:
        return None
    gaps.sort()
    median = gaps[len(gaps) // 2]
    return max(1, round(median / 2))


def round_trip_minutes(client: BartClient, station: str, via: str) -> tuple[int | None, str]:
    """Minutes to ride station -> via -> station: both legs' trip time plus one typical wait.

    Returns (minutes, basis). Minutes are None when the schedule pair is unavailable.
    """
    try:
        out = client.trips(station, via)
        back = client.trips(via, station)
    except (BartUnavailable, FileNotFoundError, KeyError) as exc:
        return None, f"not computed: {exc}"
    if not out or not back:
        return None, "not computed: empty schedule"
    wait = typical_wait_minutes(back) or 0
    total = out[0].trip_time_min + back[0].trip_time_min + wait
    basis = "live schedule" if client.live else "synthetic schedule fixture (not real BART times)"
    return total, f"{out[0].trip_time_min} out + {back[0].trip_time_min} back + {wait} wait; {basis}"


def last_train_flag(client: BartClient, origin: str, dest: str, when: datetime) -> tuple[bool | None, str]:
    """True when the schedule shows no departure after ``when``. None when unknown."""
    try:
        trips = client.trips(origin, dest)
    except (BartUnavailable, FileNotFoundError, KeyError):
        return None, "unknown: no schedule data"
    now_min = when.hour * 60 + when.minute
    later = [t for t in trips if (_parse_clock(t.orig_time) or -1) > now_min]
    if not trips:
        return None, "unknown: empty schedule"
    basis = "live schedule" if client.live else "schedule fixture (covers only the departures it lists)"
    return (len(later) == 0), basis
