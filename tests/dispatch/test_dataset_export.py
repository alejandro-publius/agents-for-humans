"""F8: make dataset produces the public CSV from a fixture archive."""

from __future__ import annotations

import csv
import json
from datetime import UTC

from le_dispatch.dataset_export import (
    COLUMNS,
    ArchiveAdapter,
    build_fixture_archive,
    duration_minutes,
    export,
)


def test_duration_rounds_up_to_the_poll():
    from datetime import datetime

    t0 = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    assert duration_minutes(t0, t0) == 0
    assert duration_minutes(t0, t0.replace(minute=7)) == 10
    assert duration_minutes(t0, t0.replace(minute=10)) == 10


def test_export_from_fixture_archive(tmp_path):
    archive = build_fixture_archive(tmp_path / "archive.sqlite")
    meta = export(ArchiveAdapter(archive), tmp_path / "public")
    csv_path = tmp_path / "public" / meta["file"]
    assert csv_path.name == "bart_elevator_outages_2026-09-05_2026-09-08.csv"
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == COLUMNS
    assert len(rows) == 5 and meta["rows"] == 5
    assert all(int(r["duration_minutes"]) % 5 == 0 for r in rows)
    assert [r["status"] for r in rows].count("open") == 1
    assert rows[0]["station"] == "DELN" and rows[0]["first_seen_utc"].endswith("Z")
    readme = (tmp_path / "public" / "README.md").read_text()
    assert "BART API" in readme and "five-minute resolution" in readme and meta["file"] in readme
    for c in COLUMNS:
        assert f"`{c}`" in readme
    side = json.loads((tmp_path / "public" / f"{meta['file']}.meta.json").read_text())
    assert side["resolution_minutes"] == 5 and side["attribution"].startswith("Data: Bay Area Rapid Transit")
    assert "riders" in readme  # the no-personal-data line


def test_adapter_query_is_the_interface(tmp_path):
    archive = build_fixture_archive(tmp_path / "archive.sqlite")
    only_resolved = ArchiveAdapter(
        archive,
        "SELECT station, elevator, description, first_seen, last_seen, resolved_at FROM outages "
        "WHERE resolved_at IS NOT NULL ORDER BY first_seen",
    )
    meta = export(only_resolved, tmp_path / "public")
    assert meta["rows"] == 4
