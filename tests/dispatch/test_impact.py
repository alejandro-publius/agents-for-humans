"""What riders faced, from the feed (le_dispatch/impact.py): the fixture archive's numbers, and the rules."""

from __future__ import annotations

import json

from le_dispatch.dataset_export import FIXTURE_ARCHIVE, build_fixture_archive
from le_dispatch.impact import RESULTS_PATH, cut_off_stations, render, run, summarise
from le_dispatch.interfaces import KBSet, load_kb


def test_the_fixture_archive_summarises_to_the_committed_numbers(tmp_path):
    archive = tmp_path / "archive.sqlite"
    build_fixture_archive(archive)
    doc = run(archive, load_kb())
    committed = json.loads(RESULTS_PATH.read_text())
    for key in ("outages", "stations", "elevators", "elevator_hours", "median_minutes", "open_at_export"):
        assert doc[key] == committed[key], key
    assert doc["evenings_with_an_outage_in_progress"] == committed["evenings_with_an_outage_in_progress"]
    assert doc["stations_cut_off"] == committed["stations_cut_off"] and doc["provenance"]["claimable"] is False
    text = render(doc)
    assert f"{doc['outages']} elevator outages at {doc['stations']} stations" in text
    assert "still open at export" in text and "\u2014" not in text
    assert FIXTURE_ARCHIVE.name == "archive_fixture.sqlite"


def test_a_station_is_cut_off_only_while_every_listed_elevator_is_out():
    kb = KBSet(stations=frozenset({"AAA", "BBB"}), elevators=frozenset({"AAA-E1", "AAA-E2", "BBB-E1", "BBB-E2"}))
    rows = [
        {
            "station": "AAA",
            "elevator": "AAA-E1",
            "first_seen_utc": "2026-09-05T10:00Z",
            "last_seen_utc": "2026-09-05T12:00Z",
        },
        {
            "station": "AAA",
            "elevator": "AAA-E2",
            "first_seen_utc": "2026-09-05T11:30Z",
            "last_seen_utc": "2026-09-05T13:00Z",
        },
        {
            "station": "BBB",
            "elevator": "BBB-E1",
            "first_seen_utc": "2026-09-05T10:00Z",
            "last_seen_utc": "2026-09-05T12:00Z",
        },
    ]
    cut = cut_off_stations(rows, kb)
    assert cut == [{"station": "AAA", "elevators": ["AAA-E1", "AAA-E2"], "minutes_cut_off": 30}]  # the overlap only
    for r in rows:
        r.update({"description": "", "resolved_at_utc": "", "duration_minutes": 120, "status": "resolved"})
    doc = summarise(rows, kb, cases=[])
    assert doc["stations_cut_off_count"] == 1 and doc["outages"] == 3 and doc["elevators_with_a_case"] == 0
    assert doc["evenings_with_an_outage_in_progress"] == 0  # every outage ended before nine in the evening local


def test_a_fixture_run_never_overwrites_the_real_archives_numbers(tmp_path, monkeypatch):
    """The laptop's `make impact IMPACT_ARGS=--archive ...` numbers survive a `make impact` typed without
    them, and the main repo's CI, which has no archive, leaves the file as committed."""
    from le_dispatch import interfaces
    from le_dispatch.impact import write

    archive = tmp_path / "archive.sqlite"
    build_fixture_archive(archive)
    fixture_doc = run(FIXTURE_ARCHIVE if FIXTURE_ARCHIVE.exists() else archive, load_kb())
    if fixture_doc["provenance"]["archive"] != "fixture":  # the fixture archive had not been built yet
        build_fixture_archive(FIXTURE_ARCHIVE)
        fixture_doc = run(FIXTURE_ARCHIVE, load_kb())
    assert fixture_doc["provenance"]["archive"] == "fixture" and fixture_doc["provenance"]["claimable"] is False
    real_doc = run(archive, load_kb())  # any other file is "the real archive" to the provenance
    assert real_doc["provenance"]["archive"] == "archive.sqlite"
    assert real_doc["provenance"]["claimable"] is False  # the fixture KB and cases: a mixed run is not claimable
    monkeypatch.setenv(interfaces.KB_EXPORT_ENV, str(tmp_path / "kb.json"))
    monkeypatch.setenv(interfaces.CASES_EXPORT_ENV, str(tmp_path / "cases.json"))
    (tmp_path / "kb.json").write_text((interfaces.FIXTURES / "kb.json").read_text())
    (tmp_path / "cases.json").write_text((interfaces.FIXTURES / "cases.json").read_text())
    real_doc = run(archive, load_kb())
    assert real_doc["provenance"]["claimable"] is True  # a real archive and real exports
    out = tmp_path / "outage_week.json"
    assert write(real_doc, out) is True
    before = out.read_text()
    assert write(fixture_doc, out) is False and out.read_text() == before  # kept
    assert write(real_doc, out) is True  # a real run may always write
    fresh = tmp_path / "fresh.json"
    assert write(fixture_doc, fresh) is True  # nothing real there to keep
