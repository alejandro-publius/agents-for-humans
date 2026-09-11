"""C1. Rider app: register a trip, replay the archive into the inbox, read it back. Offline."""

from fastapi.testclient import TestClient

from app import main as app_main
from app.replay import replay
from app.store import RiderStore
from src.poller import connect


def _client(tmp_path):
    app_main.configure(tmp_path / "riders.sqlite", tmp_path / "outages.sqlite")
    return TestClient(app_main.app)


def test_register_trip_lands_in_riders_sqlite(tmp_path):
    client = _client(tmp_path)
    r = client.post(
        "/trips",
        data={
            "rider_id": "alex",
            "origin": "sanl",
            "dest": "embr",
            "days": ["Mon", "Fri"],
            "needs": "elevator, no_bus",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    trips = RiderStore(tmp_path / "riders.sqlite").trips("alex")
    assert trips[0]["origin"] == "SANL" and trips[0]["dest"] == "EMBR"
    assert trips[0]["days"] == ["Mon", "Fri"] and trips[0]["needs"] == ["elevator", "no_bus"]
    assert client.get("/api/trips").json()[0]["rider_id"] == "alex"


def test_unknown_station_is_rejected(tmp_path):
    client = _client(tmp_path)
    r = client.post("/trips", data={"origin": "ZZZZ", "dest": "EMBR"}, follow_redirects=False)
    assert r.status_code == 400


def test_replay_populates_inbox_and_timeline_offline(tmp_path, no_network):
    client = _client(tmp_path)
    store = RiderStore(tmp_path / "riders.sqlite")
    store.seed_demo()
    stats = replay(store, connect(tmp_path / "outages.sqlite"))

    assert stats["snapshots"] == 4 and stats["new_outages"] == 4  # DELN, SANL, PLZA, EMBR
    assert stats["decisions"] == 4 * 2  # every new outage x both demo trips
    assert stats["sent"] >= 2  # SANL platform (SF direction) hits trip 1; EMBR street hits trips 1 and 2
    inbox = client.get("/api/inbox").json()
    sent = [r for r in inbox if r["sent"]]
    assert any(r["fragment"].startswith("SANL") and r["top_option"] == "backtracking" for r in sent)
    assert all(r["ranked_options"] and r["reasoning"] for r in sent)
    quiet = [r for r in inbox if not r["sent"]]
    assert any(r["condition"] == "not_on_trip" for r in quiet)
    tl = client.get("/api/timeline").json()
    assert len(tl) == 4 and tl[0]["active"] == ["DELN: Platform - Richmond"] and tl[-1]["active"] == []
    assert no_network.attempts == []
    page = client.get("/").text
    assert "Register a trip" in page and "Replay timeline" in page
