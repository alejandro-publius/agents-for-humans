"""C3. The same outage yields different top options for riders with different preferences."""

from datetime import datetime

from app.store import RiderStore
from bart import BartClient
from policy import LocalJsonPreferenceStore, Outage, Preferences, Trip, assess, preference_store
from policy.sun import PACIFIC

CLIENT = BartClient(api_key=None)
SANL_SF = "PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS)"
NIGHT = datetime(2026, 9, 12, 23, 30, tzinfo=PACIFIC)
DUSK = datetime(2026, 9, 12, 20, 30, tzinfo=PACIFIC)  # after sunset (19:21), trains still running
MORNING = datetime(2026, 9, 12, 8, 0, tzinfo=PACIFIC)


def _trip(prefs: Preferences) -> Trip:
    return Trip("SANL", "EMBR", needs=frozenset({"elevator"}) | prefs.needs())


def test_same_outage_two_riders_two_top_options_at_last_train():
    outage = Outage("SANL", SANL_SF)
    rider_a = assess(_trip(Preferences()), outage, NIGHT, CLIENT)
    rider_b = assess(_trip(Preferences(avoid_buses=True)), outage, NIGHT, CLIENT)
    assert rider_a.top_option == "transit"
    assert rider_b.top_option == "mitigation_trip"
    assert rider_a.top_option != rider_b.top_option


def test_never_after_dark_ranks_mitigation_trip_first_after_sunset():
    outage = Outage("SANL", SANL_SF)
    rider_a = assess(_trip(Preferences()), outage, DUSK, CLIENT)
    rider_b = assess(_trip(Preferences(never_after_dark=True)), outage, DUSK, CLIENT)
    assert rider_a.flags["after_dark"] and rider_a.top_option == "backtracking"
    assert rider_b.top_option == "mitigation_trip"
    assert any("never after dark" in n for n in rider_b.notes)


def test_larger_elevator_need_skips_alternate_elevator_option():
    outage = Outage("12TH", "STREET ELEVATOR (14TH STREET/OGAWA PLAZA)")
    trip_a = Trip("12TH", "EMBR")
    larger = Preferences(needs_larger_elevator=True).needs()
    trip_b = Trip("12TH", "EMBR", needs=frozenset({"elevator"}) | larger)
    a = assess(trip_a, outage, MORNING, CLIENT)
    b = assess(trip_b, outage, MORNING, CLIENT)
    assert a.top_option == "alternate_elevator" and b.top_option == "transit"
    assert "larger elevator" in b.ranked_options[0].reason


def test_local_store_round_trip_and_factory_without_credentials(tmp_path, monkeypatch):
    for var in ("AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_BEARER_TOKEN_BEDROCK", "AGENTCORE_MEMORY_ID"):
        monkeypatch.delenv(var, raising=False)
    store = preference_store(tmp_path / "prefs.json")
    assert isinstance(store, LocalJsonPreferenceStore)
    store.set("rachel", Preferences(avoid_buses=True, notes="scooter"))
    again = LocalJsonPreferenceStore(tmp_path / "prefs.json")
    assert again.get("rachel") == Preferences(avoid_buses=True, notes="scooter")
    assert again.get("nobody") == Preferences()
    assert again.all()["rachel"].needs() == frozenset({"elevator", "no_bus"})


def test_rider_store_folds_preferences_into_the_policy_trip(tmp_path):
    rs = RiderStore(tmp_path / "riders.sqlite")
    rs.add_trip("rachel", "SANL", "EMBR")
    rs.set_preferences("rachel", Preferences(avoid_buses=True))
    trip = rs.as_policy_trip(rs.trips("rachel")[0])
    assert "no_bus" in trip.needs
