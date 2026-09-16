"""E8. The dataset exporter writes a header, attribution, README line, and refuses thin archives."""

from datetime import UTC, datetime, timedelta

import pytest

from bart import BartClient
from bart.client import FIXTURES_DIR
from scripts.dataset import COLUMNS, export
from src.poller import connect, poll_once


def _synthetic_archive(db_path, polls: int):
    conn = connect(db_path)
    client = BartClient(api_key=None)
    t0 = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
    files = (
        ["elev_sample.json"] * 3 + ["elev_multi.json"] * 5 + ["elev_changed.json"] * 3 + ["elev_none.json"]
    )
    for i in range(polls):
        poll_once(
            client, conn, fixture=FIXTURES_DIR / files[i % len(files)], now=t0 + timedelta(minutes=5 * i)
        )
    return conn


def test_export_twelve_synthetic_snapshots(tmp_path, no_network):
    _synthetic_archive(tmp_path / "outages.sqlite", 12)
    path = export(tmp_path / "outages.sqlite", tmp_path / "public")
    lines = path.read_text().splitlines()
    assert lines[0].startswith("# Source: BART Legacy API (https://api.bart.gov)")
    assert lines[1] == ",".join(COLUMNS)
    assert len(lines) - 2 >= 12  # at least one active outage row per snapshot in this synthetic archive
    assert path.name == "bart_elevator_outages_2026-09-12_2026-09-12.csv"
    readme = (tmp_path / "public" / "README.md").read_text()
    assert path.name in readme and "12 snapshots" in readme and "5-minute" in readme
    export(tmp_path / "outages.sqlite", tmp_path / "public")  # idempotent README line
    assert (tmp_path / "public" / "README.md").read_text().count(path.name) == 1


def test_thin_archive_is_refused(tmp_path, no_network):
    _synthetic_archive(tmp_path / "outages.sqlite", 3)
    with pytest.raises(SystemExit, match="need at least 12"):
        export(tmp_path / "outages.sqlite", tmp_path / "public")
    with pytest.raises(SystemExit, match="no archive database"):
        export(tmp_path / "missing.sqlite", tmp_path / "public")
