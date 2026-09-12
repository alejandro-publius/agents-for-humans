"""Export the archived BART elevator outage feed as a public CSV dataset.

    make dataset          # data/public/bart_elevator_outages_<start>_<end>.csv from the live archive

Columns (one row per outage per snapshot in which it was active):
    snapshot_at   ISO-8601 UTC time the feed was polled (5-minute resolution when polled by make archive)
    station_abbr  BART station code resolved from the fragment by code (blank when unresolved)
    kb_elevator   the elevator name as BART's accessible-path page lists it (blank when ambiguous)
    fragment      BART's own text for the outage, e.g. "DELN: Platform - Richmond"
    first_seen    first snapshot in which this outage appeared
    cleared_at    first snapshot in which it was gone (blank while active)
    source        the feed source recorded by the poller (live or fixture)

Attribution: outage data from the BART Legacy API (https://api.bart.gov), (c) San Francisco Bay
Area Rapid Transit District, used under BART's API license agreement; station and elevator names
from bart.gov accessible-path pages. Time resolution is the polling interval, not BART's.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "archive" / "outages.sqlite"
OUT_DIR = REPO_ROOT / "data" / "public"
MIN_SNAPSHOTS = 12
ATTRIBUTION = (
    "Source: BART Legacy API (https://api.bart.gov), (c) San Francisco Bay Area Rapid Transit District, "
    "under BART's API license; station and elevator names from bart.gov accessible-path pages. "
    "Resolution: one row per outage per poll; polls every 5 minutes."
)
COLUMNS = ["snapshot_at", "station_abbr", "kb_elevator", "fragment", "first_seen", "cleared_at", "source"]


def export(db: Path, out_dir: Path, min_snapshots: int = MIN_SNAPSHOTS) -> Path:
    if not db.exists():
        raise SystemExit(f"dataset: no archive database at {db}; run make archive first")
    conn = sqlite3.connect(db)
    snaps = [r[0] for r in conn.execute("SELECT DISTINCT taken_at FROM snapshots ORDER BY taken_at")]
    if len(snaps) < min_snapshots:
        raise SystemExit(
            f"dataset: {len(snaps)} snapshots in the archive; need at least {min_snapshots} (about an hour)"
        )
    outages = conn.execute(
        "SELECT fragment, station_abbr, kb_elevator, first_seen, cleared_at, source "
        "FROM outages ORDER BY first_seen, id"
    ).fetchall()
    start, end = snaps[0][:10], snaps[-1][:10]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"bart_elevator_outages_{start}_{end}.csv"
    rows = 0
    with path.open("w", newline="") as fh:
        fh.write(f"# {ATTRIBUTION}\n")
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for snap in snaps:
            for fragment, station, elevator, first_seen, cleared_at, source in outages:
                if first_seen <= snap and (cleared_at is None or snap < cleared_at):
                    writer.writerow(
                        [snap, station or "", elevator or "", fragment, first_seen, cleared_at or "", source]
                    )
                    rows += 1
    readme = out_dir / "README.md"
    line = (
        f"- `{path.name}`: {len(snaps)} snapshots from {snaps[0]} to {snaps[-1]}, {rows} rows, "
        f"columns {', '.join(COLUMNS)}; one row per outage per 5-minute poll. {ATTRIBUTION}\n"
    )
    existing = readme.read_text() if readme.exists() else "# Public datasets\n\n"
    if path.name not in existing:
        readme.write_text(existing + line)
    print(f"dataset: wrote {path} ({len(snaps)} snapshots, {rows} rows); README line added")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--min-snapshots", type=int, default=MIN_SNAPSHOTS)
    args = parser.parse_args(argv)
    export(args.db, args.out_dir, args.min_snapshots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
