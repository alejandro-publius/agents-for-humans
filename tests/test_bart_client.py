"""B2. BART client: fixtures by default, parsers are code, live path fails in one line."""

import logging
from pathlib import Path

import pytest

from bart import (
    BartClient,
    BartUnavailable,
    outage_fragments,
    parse_depart,
    parse_elevator_advisories,
    parse_etd,
    parse_stations,
)
from bart.client import FIXTURES_DIR

FIX = FIXTURES_DIR


def test_client_is_offline_without_a_key(monkeypatch):
    monkeypatch.delenv("BART_API_KEY", raising=False)
    client = BartClient()
    assert client.live is False and client.mode == "fixtures"


def test_documented_elevator_sample_parses_to_one_fragment():
    advisories = BartClient(api_key=None).elevator_advisories()
    assert len(advisories) == 1
    adv = advisories[0]
    assert adv.description == "There is 1 elevator out of service at this time: DELN: Platform - Richmond"
    assert adv.sms_text == "1 elev out of svc: DELN: plat - RICH"
    assert adv.fragments == ["DELN: Platform - Richmond"]


def test_multi_and_none_fixtures():
    client = BartClient(api_key=None)
    multi = client.elevator_advisories(fixture=FIX / "elev_multi.json")
    assert multi[0].fragments == [
        "DELN: Platform - Richmond",
        "SANL: Platform - SFO/Millbrae/Daly City",
        "PLZA: Platform - Richmond",
    ]
    none = client.elevator_advisories(fixture=FIX / "elev_none.json")
    assert none[0].fragments == []


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "There is 1 elevator out of service at this time: DELN: Platform - Richmond",
            ["DELN: Platform - Richmond"],
        ),
        (
            "There are 2 elevators out of service at this time: "
            "16TH: Street - Concourse, POWL: Concourse - Platform",
            ["16TH: Street - Concourse", "POWL: Concourse - Platform"],
        ),
        ("No elevators are out of service at this time.", []),
        ("Attention passengers: all elevators are in service.", []),
        ("", []),
    ],
)
def test_outage_fragments(text, expected):
    assert outage_fragments(text) == expected


def test_every_fixture_is_labeled_with_provenance():
    import json

    for path in sorted(FIX.glob("*.json")):
        meta = json.loads(path.read_text())["_fixture"]
        assert "source" in meta and isinstance(meta["synthetic"], bool), path.name
        if meta["synthetic"]:
            labeled = "SYNTHETIC" in meta.get("note", "") or "Authored" in meta["source"]
            assert labeled or "abbrev" in meta["source"], path.name


def test_stations_fixture_has_all_fifty():
    stations = parse_stations(BartClient(api_key=None).stations())
    assert len(stations) == 50
    assert {"name": "El Cerrito del Norte", "abbr": "DELN"} in stations


def test_depart_sample_parses_trip_times():
    trips = BartClient(api_key=None).trips("ASHB", "CIVC")
    assert trips and all(t.origin == "ASHB" and t.destination == "CIVC" for t in trips)
    assert all(t.trip_time_min > 0 for t in trips)
    assert trips[0].legs >= 1


def test_etd_and_advisories_fixtures_parse():
    client = BartClient(api_key=None)
    rows = parse_etd(client.etd("RICH"))
    assert rows and rows[0]["station"] == "RICH" and isinstance(rows[0]["minutes"], int)
    adv = client.advisories()
    assert adv["root"]["bsa"][0]["description"]["#cdata-section"] == "No advisories issued."
    access = client.station_access("12TH")
    assert access["root"]["stations"]["station"]["abbr"] == "12TH"
    description = access["root"]["stations"]["station"]["elevator_description"]["#cdata-section"]
    assert "elevator" in description.lower()


def test_live_path_fails_in_one_line_without_key_or_traceback(no_network, caplog):
    client = BartClient(api_key="NOT-A-REAL-KEY-000")
    assert client.live
    with caplog.at_level(logging.WARNING, logger="bart"), pytest.raises(BartUnavailable) as exc:
        client.elevators()
    message = str(exc.value)
    assert "unavailable" in message and "NOT-A-REAL-KEY" not in message
    warnings = [r for r in caplog.records if r.name == "bart"]
    assert len(warnings) == 1, "exactly one log line, no retries"
    assert no_network.attempts, "the live path was attempted and refused by the guard"


def test_parsers_accept_single_object_where_bart_omits_the_list():
    payload = {"root": {"bsa": {"@id": "1", "station": "BART", "type": "ELEVATOR", "description": "x"}}}
    assert parse_elevator_advisories(payload)[0].id == "1"
    trip = {"@origin": "a", "@destination": "b", "@tripTime": "7"}
    single = {"root": {"schedule": {"request": {"trip": trip}}}}
    assert parse_depart(single)[0].trip_time_min == 7


def test_fixture_dir_is_the_committed_one():
    assert Path(FIX).name == "bart" and (FIX / "README.md").exists()
