"""B5. Poller diffs snapshots and records new and cleared outages in SQLite. Offline."""

from datetime import UTC, datetime, timedelta

from bart import BartClient
from bart.client import FIXTURES_DIR
from src.poller import active_outages, connect, main, poll_once

T0 = datetime(2026, 9, 12, 7, 0, tzinfo=UTC)


def test_first_poll_inserts_and_second_poll_inserts_none(tmp_path):
    conn = connect(tmp_path / "o.sqlite")
    client = BartClient(api_key=None)
    first = poll_once(client, conn, fixture=FIXTURES_DIR / "elev_sample.json", now=T0)
    second = poll_once(client, conn, fixture=FIXTURES_DIR / "elev_sample.json", now=T0 + timedelta(minutes=5))

    assert first.fragments == ("DELN: Platform - Richmond",)
    assert (first.inserted, first.cleared, first.unchanged) == (1, 0, 0)
    assert (second.inserted, second.cleared, second.unchanged) == (0, 0, 1)
    rows = active_outages(conn)
    assert len(rows) == 1
    assert rows[0]["station_abbr"] == "DELN"
    assert rows[0]["kb_elevator"] == "PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)"
    assert rows[0]["last_seen"] > rows[0]["first_seen"]
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2


def test_changed_snapshot_records_new_and_cleared(tmp_path):
    conn = connect(tmp_path / "o.sqlite")
    client = BartClient(api_key=None)
    a = poll_once(client, conn, fixture=FIXTURES_DIR / "elev_multi.json", now=T0)
    b = poll_once(client, conn, fixture=FIXTURES_DIR / "elev_changed.json", now=T0 + timedelta(minutes=5))

    assert (a.inserted, a.cleared) == (3, 0)
    assert (b.inserted, b.cleared, b.unchanged) == (1, 1, 2)
    active = {r["fragment"] for r in active_outages(conn)}
    assert "DELN: Platform - Richmond" not in active and "EMBR: Street - Concourse" in active
    events = conn.execute("SELECT kind, fragment FROM events ORDER BY id").fetchall()
    assert ("cleared", "DELN: Platform - Richmond") in events
    assert ("new", "EMBR: Street - Concourse") in events


def test_empty_feed_clears_everything(tmp_path):
    conn = connect(tmp_path / "o.sqlite")
    client = BartClient(api_key=None)
    poll_once(client, conn, fixture=FIXTURES_DIR / "elev_multi.json", now=T0)
    r = poll_once(client, conn, fixture=FIXTURES_DIR / "elev_none.json", now=T0 + timedelta(minutes=5))
    assert r.fragments == () and r.cleared == 3 and active_outages(conn) == []


def test_cli_refuses_live_without_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("BART_API_KEY", raising=False)
    assert main(["--once", "--db", str(tmp_path / "o.sqlite")]) == 2
    assert "no BART_API_KEY" in capsys.readouterr().err


def test_cli_once_with_fixture(tmp_path, capsys):
    db = tmp_path / "o.sqlite"
    assert main(["--once", "--fixture", str(FIXTURES_DIR / "elev_sample.json"), "--db", str(db)]) == 0
    assert main(["--once", "--fixture", str(FIXTURES_DIR / "elev_sample.json"), "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "inserted=1" in out and "inserted=0" in out
