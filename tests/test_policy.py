"""B4. Trip matcher and policy engine: BART's two worked examples, flags, feasibility. Pure code."""

from datetime import date, datetime

import pytest

from bart import BartClient
from policy import Decision, Outage, Trip, assess, is_after_dark, sunset_local
from policy.engine import platform_serves_direction
from policy.sun import PACIFIC

CLIENT = BartClient(api_key=None)
MORNING = datetime(2026, 9, 12, 8, 0, tzinfo=PACIFIC)
NIGHT = datetime(2026, 9, 12, 23, 30, tzinfo=PACIFIC)

SANL_SF_PLATFORM = "PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS)"
SANL_OTHER_PLATFORM = "PLATFORM 1 ELEVATOR (DUBLIN, BERRYESSA DIRECTIONS)"
PLZA_RICHMOND_PLATFORM = "PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)"


def test_bart_example_boarding_at_san_leandro_toward_sf():
    """BART's page: boarding at San Leandro toward SF with the SF-direction platform elevator out."""
    trip = Trip(origin="SANL", dest="EMBR")
    d = assess(trip, Outage("SANL", SANL_SF_PLATFORM), MORNING, CLIENT)

    assert isinstance(d, Decision) and d.affected is True
    assert d.condition == "cant_enter"
    assert d.documented_option["text"].startswith("Take the Platform 1 elevator to the opposite platform")
    assert "Bay Fair" in d.documented_option["text"]
    assert d.documented_option["option_label"] == "backtracking"
    assert d.top_option == "backtracking"
    top = d.ranked_options[0]
    assert top.option == "backtracking" and top.feasible and top.added_minutes == 4 + 4 + 6
    assert "synthetic schedule fixture" in top.minutes_basis
    order = [o.option for o in d.ranked_options]
    assert order == ["backtracking", "transit", "mitigation_trip", "mitigation_shuttle"]


def test_bart_example_exiting_at_el_cerrito_plaza_from_sf():
    """BART's page: exiting at El Cerrito Plaza from SF with the Richmond-direction platform elevator out."""
    trip = Trip(origin="EMBR", dest="PLZA")
    d = assess(trip, Outage("PLZA", PLZA_RICHMOND_PLATFORM), MORNING, CLIENT)

    assert d.affected is True and d.condition == "cant_exit"
    assert d.documented_option["text"] == (
        "Continue on BART to El Cerrito del Norte and return to El Cerrito Plaza. "
        "Exit using Platform 2 elevator."
    )
    assert d.top_option == "backtracking"
    assert d.ranked_options[0].added_minutes == 3 + 3 + 6
    assert d.flags["direction_source"].endswith("depart_EMBR_PLZA")


def test_wrong_direction_platform_is_not_affected():
    d = assess(Trip("SANL", "EMBR"), Outage("SANL", SANL_OTHER_PLATFORM), MORNING, CLIENT)
    assert d.affected is False and d.condition == "other_direction"


def test_station_not_on_trip_is_not_affected():
    d = assess(Trip("SANL", "EMBR"), Outage("PLZA", PLZA_RICHMOND_PLATFORM), MORNING, CLIENT)
    assert d.affected is False and d.condition == "not_on_trip" and d.top_option is None


def test_unknown_direction_without_schedule_is_reported_not_guessed():
    d = assess(Trip("SANL", "ASHB"), Outage("SANL", SANL_SF_PLATFORM), MORNING, CLIENT)
    assert d.affected is None and d.condition == "unknown_direction"
    assert d.flags["direction_source"].startswith("unknown")


def test_last_train_makes_backtracking_infeasible_and_transit_next():
    d = assess(Trip("SANL", "EMBR"), Outage("SANL", SANL_SF_PLATFORM), NIGHT, CLIENT)
    assert d.flags["last_train"] is True
    assert d.ranked_options[0].option == "backtracking" and d.ranked_options[0].feasible is False
    assert d.top_option == "transit"


def test_rider_who_cannot_use_buses_at_last_train_gets_mitigation_trip():
    trip = Trip("SANL", "EMBR", needs=frozenset({"elevator", "no_bus"}))
    d = assess(trip, Outage("SANL", SANL_SF_PLATFORM), NIGHT, CLIENT)
    assert d.top_option == "mitigation_trip"
    assert "accessible van" in next(o.text for o in d.ranked_options if o.option == "mitigation_trip")


def test_street_elevator_affects_boarding_regardless_of_direction():
    d = assess(Trip("EMBR", "PLZA"), Outage("EMBR", "STREET ELEVATOR"), MORNING, CLIENT)
    assert d.affected is True and d.condition == "cant_enter"
    assert d.documented_option["option_label"] == "transit"
    assert d.top_option == "transit"


def test_after_dark_flag_uses_local_sunset():
    sunset = sunset_local(date(2026, 9, 12))
    assert sunset.tzinfo is not None and 18 <= sunset.hour <= 20  # Oakland, mid-September
    assert sunset.date() == date(2026, 9, 12)
    assert is_after_dark(NIGHT) is True and is_after_dark(MORNING) is False
    assert assess(Trip("SANL", "EMBR"), Outage("SANL", SANL_SF_PLATFORM), NIGHT, CLIENT).flags["after_dark"]


@pytest.mark.parametrize(
    "heading, head, expected",
    [
        (SANL_SF_PLATFORM, "Daly City", True),
        (SANL_SF_PLATFORM, "Richmond", True),
        (SANL_OTHER_PLATFORM, "Daly City", False),
        ("PLATFORMS 1 AND 2 ELEVATOR (ALL DESTINATIONS)", "Antioch", True),
        ("PLATFORM ELEVATOR", "Antioch", None),
    ],
)
def test_platform_direction_matching(heading, head, expected):
    assert platform_serves_direction(heading, head) is expected


def test_unknown_station_or_elevator_is_refused():
    trip = Trip("SANL", "EMBR")
    assert assess(trip, Outage("ZZZZ", "X"), MORNING, CLIENT).condition == "unknown_station"
    assert assess(trip, Outage("SANL", "NOPE"), MORNING, CLIENT).condition == "unknown_elevator"
