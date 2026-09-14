"""Portability: the harness is agency-agnostic.

Everything agency-specific enters through two JSON shapes (the KB and the
cases, see interfaces.py) and one callable (the policy). `synthetic_agency`
builds a second, deliberately different agency in memory (other station
codes, a different published option order, a different label subset,
other minutes) so tests can run the whole pipeline on it without touching
a line of code: gates, red team, Cedar, dataset export, convergence,
messages. No real agency is modelled; this is a proof of shape, not a
second transit product.
"""

from __future__ import annotations

from typing import Any

from .interfaces import Case, FixturePolicy, KBSet


def synthetic_agency(
    name: str = "agency-b",
    n_stations: int = 12,
    order: tuple[str, ...] = ("backtracking", "alternate_elevator", "transit"),
) -> tuple[KBSet, list[Case], FixturePolicy]:
    """A small synthetic agency: 12 stations, 2 elevators each, 2 options per
    elevator, labels in the agency's own published order."""
    stations = [f"{chr(ord('A') + i)}TN{i % 10}" for i in range(n_stations)]  # ATN0, BTN1, ...
    elevators = [f"{s}-E{k}" for s in stations for k in (1, 2)]
    kb = KBSet(
        stations=frozenset(stations),
        elevators=frozenset(elevators),
        option_labels=order,
        source=f"synthetic {name}",
        frozen_tag=f"{name}-fixture",
        station_names={s: f"{s[0]} Town" for s in stations},  # the names a rider hears: "A Town", "B Town", ...
    )
    minutes = {"backtracking": 9, "alternate_elevator": 3, "transit": 25}
    text = {
        "backtracking": "Ride one stop beyond and return on the far platform, where the lift runs.",
        "alternate_elevator": "Use the second lift by the north entrance; the walkway is step-free.",
        "transit": "Take the agency's bus bridge from the plaza; the fare is honored.",
    }
    cases: list[Case] = []
    labels = list(order)
    for i, ev in enumerate(elevators):
        for slot in range(2):
            label = labels[(i + slot) % len(labels)]
            cases.append(
                Case(
                    case_id=f"{name}-{len(cases) + 1:03d}",
                    station=ev.split("-")[0],
                    elevator=ev,
                    label=label,
                    option_text=text[label],
                    added_minutes=minutes[label],
                    source_url=f"https://example.invalid/{name}/{ev.split('-')[0].lower()}",
                )
            )
    return kb, cases, FixturePolicy(cases, kb)


def kb_json(kb: KBSet) -> dict[str, Any]:
    """The KB in the documented JSON shape, for gen_cedar and the exporters."""
    return {
        "source": kb.source,
        "frozen_tag": kb.frozen_tag,
        "stations": sorted(kb.stations),
        "elevators": sorted(kb.elevators),
        "option_labels": list(kb.option_labels),
        "station_names": dict(kb.station_names),
    }
