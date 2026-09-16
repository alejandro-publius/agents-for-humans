"""C2. The quiet report counts from the replayed inbox and the outage feed."""

import json

from app.replay import replay
from app.store import RiderStore
from src.poller import connect
from src.report import main, rider_report


def _replayed(tmp_path):
    store = RiderStore(tmp_path / "riders.sqlite")
    store.seed_demo()
    replay(store, connect(tmp_path / "outages.sqlite"))
    return store


def test_four_numbers_for_the_demo_rider(tmp_path, no_network):
    store = _replayed(tmp_path)
    r = rider_report(store, tmp_path / "outages.sqlite", "demo")
    assert r["registered_stations"] == ["EMBR", "PLZA", "SANL"]
    assert r["outages_on_feed"] == 4
    assert r["outages_touching_your_stations"] == 3  # SANL, PLZA, EMBR; not DELN
    assert r["outages_touching_your_trips"] == 3
    assert r["interruptions_sent"] == 4  # EMBR street elevator hits both trips
    assert r["bart_style_station_alerts"] == 6  # 3 starts + 3 clearances
    assert r["quiet_decisions"] == 4


def test_cli_prints_and_writes_results(tmp_path, capsys, no_network):
    _replayed(tmp_path)
    out = tmp_path / "interruptions.json"
    args = [
        "--rider", "demo",
        "--db", str(tmp_path / "riders.sqlite"),
        "--outages-db", str(tmp_path / "outages.sqlite"),
        "--out", str(out),
    ]  # fmt: skip
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert "3 outages touched your stations, 3 touched your trips, 4 interruptions sent" in printed
    assert json.loads(out.read_text())["rider"]["bart_style_station_alerts"] == 6
    assert main(["--rider", "nobody", "--db", str(tmp_path / "riders.sqlite")]) == 2


def test_quiet_metric_and_opening_line(tmp_path, capsys, no_network):
    from src.report import quiet_metric, write_quiet

    store = _replayed(tmp_path)
    q = quiet_metric(store, tmp_path / "outages.sqlite", "test")
    assert q["riders"] == 1 and q["snapshots"] == 4 and q["decisions"] == 8 and q["interruptions"] == 4
    assert 0 < q["days_covered"] < 1  # the synthetic archive spans 15 minutes
    assert q["interruptions_per_rider_week"] == round(4 / (q["days_covered"] / 7), 2)
    out = tmp_path / "quiet.json"
    entries = write_quiet(store, tmp_path / "outages.sqlite", out)
    assert set(entries) == {"synthetic_replay", "archive"}
    assert entries["archive"].get("status") in (None, "awaiting archive")
    main(
        [
            "--rider",
            "demo",
            "--db",
            str(tmp_path / "riders.sqlite"),
            "--outages-db",
            str(tmp_path / "outages.sqlite"),
            "--out",
            str(tmp_path / "i.json"),
        ]
    )
    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line.endswith("days, 4 interruptions, 8 decisions")
