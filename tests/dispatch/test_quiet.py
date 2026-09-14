"""F4: the quiet metric from the synthetic riders replay."""

from __future__ import annotations

import json

from le_dispatch.quiet import (
    active_outages,
    load_fixture_week,
    opening_line,
    quiet_metric,
    replay_week,
    weekly_report,
    write_results,
)


def test_active_outages_at_five_minute_resolution():
    _, schedule = load_fixture_week()
    assert active_outages(schedule, 0, "07:40") == ("DELN-E1",)
    assert active_outages(schedule, 0, "11:35") == ("PLZA-E2",)
    assert active_outages(schedule, 6, "12:00") == ("BALB-E1",)


def test_replay_week_counts_and_opening_line(fixture_stack, tmp_path):
    kb, policy = fixture_stack
    riders, schedule = load_fixture_week()
    events = replay_week(kb, policy, riders, schedule, workdir=tmp_path)
    metric = quiet_metric(events, schedule["days"], len(riders["riders"]))
    assert metric["days"] == 7 and metric["riders"] == 3 and metric["rider_weeks"] == 3.0
    assert metric["trips_checked"] == sum(1 for e in events if e.kind in ("quiet", "plan_sent"))
    assert metric["interruptions"] == metric["decisions"]  # every question got an answer
    assert 1 <= metric["interruptions"] <= 4  # the fixture week has a few after-dark and one last-train case
    assert metric["plans_sent_in_background"] > metric["interruptions"]  # most work happens silently
    assert metric["opening_line"] == opening_line(7, metric["interruptions"], metric["decisions"])
    assert metric["opening_line"].startswith("7 days, ")
    # the same case never interrupts twice: interrupts have distinct case keys
    keys = [e.case_key for e in events if e.kind == "interrupt"]
    assert len(keys) == len(set(keys))
    doc = write_results(metric, events, tmp_path / "quiet.json", provenance="test")
    assert doc["provenance"]["claimable"] is False
    report = weekly_report(doc)
    assert report.splitlines()[0] == metric["opening_line"]
    assert (
        json.loads((tmp_path / "quiet.json").read_text())["interrupts_per_rider_week"]
        == metric["interrupts_per_rider_week"]
    )


def test_daytime_outages_never_ask(fixture_stack, tmp_path):
    kb, policy = fixture_stack
    riders, schedule = load_fixture_week()
    daytime = {"days": 7, "outages": [o for o in schedule["outages"] if o["to"] <= "18:00"]}
    events = replay_week(kb, policy, riders, daytime, workdir=tmp_path)
    metric = quiet_metric(events, 7, 3)
    assert metric["interruptions"] == 0 and metric["decisions"] == 0
    assert metric["opening_line"] == "7 days, 0 interruptions, 0 decisions"


def test_the_archive_week_becomes_a_schedule_and_the_same_replay_runs_on_it(fixture_stack, tmp_path):
    """The archive's public rows become the schedule the replay takes: day 0 is the earliest local date,
    an outage that crosses local midnight is cut into one segment per day, minutes are floored to the
    poller's five; the replay runs on it and the results say which week and whose riders."""
    from le_dispatch.dataset_export import FIXTURE_ARCHIVE, ArchiveAdapter, build_fixture_archive, to_public_rows
    from le_dispatch.quiet import schedule_from_rows

    if not FIXTURE_ARCHIVE.exists():
        build_fixture_archive(FIXTURE_ARCHIVE)
    rows = to_public_rows(ArchiveAdapter(FIXTURE_ARCHIVE).rows())
    schedule = schedule_from_rows(rows)
    assert schedule["days"] == 4 and len(schedule["outages"]) == 8 and "outages" in schedule["source"]
    by_elevator: dict[str, list[dict]] = {}
    for o in schedule["outages"]:
        by_elevator.setdefault(o["elevator"], []).append(o)
    assert by_elevator["DELN-E1"] == [{"day": 0, "elevator": "DELN-E1", "from": "05:00", "to": "11:25"}]  # 12:00Z
    plaza = by_elevator["PLZA-E2"]  # 24 hours from 13:00Z: cut at local midnight into two segments
    assert [(o["day"], o["from"], o["to"]) for o in plaza] == [(0, "06:00", "23:59"), (1, "00:00", "06:00")]
    assert all(int(o["from"][-2:]) % 5 == 0 for o in schedule["outages"])
    assert active_outages(schedule, 0, "07:40") == ("DELN-E1", "PLZA-E2")
    kb, policy = fixture_stack
    riders, _ = load_fixture_week()
    events = replay_week(kb, policy, riders, schedule, workdir=tmp_path)
    metric = quiet_metric(events, schedule["days"], len(riders["riders"]))
    assert metric["days"] == 4 and metric["plans_sent"] >= 1
    out = tmp_path / "quiet.json"
    doc = write_results(metric, events, out, provenance="test", week="archive x", riders="synthetic")
    assert doc["provenance"]["week"] == "archive x" and doc["provenance"]["claimable"] is False
    assert "archive" in doc["provenance"]["note"] and "--riders" in doc["provenance"]["note"]


def test_a_synthetic_replay_never_overwrites_the_archives_week(tmp_path, fixture_stack):
    """`make report` without REPORT_ARGS, or the main repo's CI, leaves the archive's replay as committed."""
    kb, policy = fixture_stack
    riders, schedule = load_fixture_week()
    events = replay_week(kb, policy, riders, schedule, workdir=tmp_path)
    metric = quiet_metric(events, schedule["days"], len(riders["riders"]))
    out = tmp_path / "quiet.json"
    write_results(metric, events, out, provenance="archive", week="archive x, 7 days", riders="synthetic")
    before = out.read_text()
    kept = write_results(metric, events, out, provenance="synthetic", week="synthetic", riders="synthetic")
    assert "kept" in kept["provenance"] and out.read_text() == before
    again = write_results(metric, events, out, provenance="archive", week="archive y", riders="real")
    assert "kept" not in again["provenance"] and json.loads(out.read_text())["provenance"]["week"] == "archive y"
