"""make report: replay the week (synthetic, or the archive's with --archive), write results/quiet.json, print it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.interfaces import fixture_policy  # noqa: E402
from le_dispatch.quiet import (  # noqa: E402
    RESULTS_PATH,
    load_fixture_week,
    quiet_metric,
    replay_week,
    weekly_report,
    write_results,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RESULTS_PATH))
    ap.add_argument("--archive", default=None, help="sqlite outage archive: the replay runs on the week it recorded")
    ap.add_argument("--query-file", default=None, help="SQL returning the documented columns for the real archive")
    ap.add_argument("--riders", default=None, help="a riders JSON shaped like fixtures/riders.json (else synthetic)")
    ap.add_argument("--tz", default="America/Los_Angeles", help="the agency's local time for after dark and last train")
    args = ap.parse_args(argv)
    kb, policy = fixture_policy()
    riders, schedule = load_fixture_week()
    week, who = "synthetic", "synthetic"
    if args.riders:
        riders = json.loads(Path(args.riders).read_text())
        who = "real trips"
    if args.archive:
        from le_dispatch.dataset_export import ArchiveAdapter, to_public_rows
        from le_dispatch.quiet import schedule_from_rows

        query = Path(args.query_file).read_text() if args.query_file else None
        adapter = ArchiveAdapter(Path(args.archive), query) if query else ArchiveAdapter(Path(args.archive))
        schedule = schedule_from_rows(to_public_rows(adapter.rows()), args.tz)
        week = f"archive {Path(args.archive).name}, {schedule['days']} days, {len(schedule['outages'])} segments"
    provenance = (
        "dispatch sandbox, synthetic riders and outage week"
        if week == "synthetic"
        else f"the archive's week ({week}) replayed for {who} riders"
    )
    events = replay_week(kb, policy, riders, schedule)
    metric = quiet_metric(events, schedule["days"], len(riders["riders"]))
    doc = write_results(metric, events, Path(args.out), provenance=provenance, week=week, riders=who)
    print(weekly_report(doc))
    if doc["provenance"].get("kept"):
        print(f"\nleft {args.out} as committed: {doc['provenance']['kept']}")
    else:
        print(f"\nwrote {args.out} (claimable: {doc['provenance']['claimable']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
