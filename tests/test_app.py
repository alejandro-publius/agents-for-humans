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


def test_night_replay_writes_a_decision_card_and_answering_resumes(tmp_path, no_network):
    """E1 in the app: a pending decision row with the card; POST answer resumes from the persisted session."""
    from bart.client import FIXTURES_DIR

    client = _client(tmp_path)
    store = RiderStore(tmp_path / "riders.sqlite")
    store.seed_demo()
    stats = replay(
        store, connect(tmp_path / "outages.sqlite"), FIXTURES_DIR / "archive_night_test.json",
        sessions_dir=tmp_path / "sessions",
    )  # fmt: skip
    assert stats["pending"] >= 1
    pending = [r for r in client.get("/api/inbox").json() if r["condition"] == "pending_decision"]
    assert pending, "the SANL night outage on the SANL->EMBR trip needs a rider decision"
    row = next(r for r in pending if r["station"] == "SANL")
    assert row["card"]["flags"] == ["after_dark", "last_train"] and row["card"]["recommended"] == "transit"
    assert row["session_id"] and row["interrupt_id"] and row["message"] is None

    r = client.post(f"/decisions/{row['id']}", data={"answer": "accept"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"] and body["error"] is None
    updated = store.inbox_row(row["id"])
    assert updated["answer"] == "accept" and updated["condition"] == "cant_enter" and updated["sent"] == 1
    assert store.decisions("demo") == {row["card"]["case_key"]: "accept"}

    # the same case, replayed again for the same rider, no longer pauses
    store.clear_inbox()
    stats2 = replay(
        store, connect(tmp_path / "outages2.sqlite"), FIXTURES_DIR / "archive_night_test.json",
        sessions_dir=tmp_path / "sessions2",
    )  # fmt: skip
    assert stats2["pending"] == stats["pending"] - 1, "only the answered case stops pausing"
    still = [r for r in store.inbox() if r["condition"] == "pending_decision"]
    assert all(r["card"]["case_key"] != row["card"]["case_key"] for r in still)
    assert client.post(f"/decisions/{row['id']}", data={"answer": "accept"}).status_code == 400
    assert no_network.attempts == []
