"""BART Legacy API client (JSON mode) with offline fixtures. Code only; no model calls."""

from bart.client import (
    BartClient,
    BartUnavailable,
    ElevatorAdvisory,
    Trip,
    outage_fragments,
    parse_depart,
    parse_elevator_advisories,
    parse_etd,
    parse_stations,
)

__all__ = [
    "BartClient",
    "BartUnavailable",
    "ElevatorAdvisory",
    "Trip",
    "outage_fragments",
    "parse_depart",
    "parse_elevator_advisories",
    "parse_etd",
    "parse_stations",
]
