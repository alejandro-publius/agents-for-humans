"""F8: public dataset export from the outage archive (E8), coded against a fixture.

The poller watches BART's elevator outage feed every five minutes and diffs
snapshots into sqlite. This module turns that archive into a public CSV:

    data/public/bart_elevator_outages_<start>_<end>.csv

with a header row, plus data/public/README.md (attribution, columns,
five-minute resolution) and a sidecar .meta.json.

Archive interface: an ArchiveAdapter holds one SQL query that must return
the documented columns (station, elevator, description, first_seen,
last_seen, resolved_at; ISO 8601 UTC). The fixture schema below is what
the dispatch session tested against; the laptop points the adapter at the
real archive with its own query. The dispatch session never read
data/archive/.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "data" / "public"
FIXTURE_ARCHIVE = ROOT / "fixtures" / "archive_fixture.sqlite"
RESOLUTION_MINUTES = 5

ATTRIBUTION = (
    "Data: Bay Area Rapid Transit (BART) elevator status feed, via the BART API (api.bart.gov), "
    "polled every five minutes by Last Elevator. Check BART's API license terms before redistributing."
)

COLUMNS = [
    "station",
    "elevator",
    "description",
    "first_seen_utc",
    "last_seen_utc",
    "resolved_at_utc",
    "duration_minutes",
    "status",
]

COLUMN_NOTES = {
    "station": "BART station abbreviation as reported by the feed",
    "elevator": "elevator id as parsed from the feed text",
    "description": "the outage text as published by BART",
    "first_seen_utc": "first snapshot that listed the outage (ISO 8601, UTC)",
    "last_seen_utc": "last snapshot that listed the outage (ISO 8601, UTC)",
    "resolved_at_utc": "first snapshot that no longer listed it, empty if still open at export",
    "duration_minutes": "last_seen minus first_seen, rounded up to the five-minute poll",
    "status": "resolved or open",
}

FIXTURE_SCHEMA = """
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE outages (
    id INTEGER PRIMARY KEY,
    station TEXT NOT NULL,
    elevator TEXT NOT NULL,
    description TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    resolved_at TEXT
);
"""

DEFAULT_QUERY = """
SELECT station, elevator, description, first_seen, last_seen, resolved_at
FROM outages
ORDER BY first_seen, station, elevator
"""


@dataclass
class ArchiveAdapter:
    path: Path
    query: str = DEFAULT_QUERY

    def rows(self) -> list[dict[str, Any]]:
        con = sqlite3.connect(str(self.path))
        try:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(self.query)]
        finally:
            con.close()


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(dt: datetime | None) -> str:
    return dt.astimezone(UTC).isoformat(timespec="minutes").replace("+00:00", "Z") if dt else ""


def duration_minutes(first_seen: datetime, last_seen: datetime) -> int:
    minutes = max(0, int((last_seen - first_seen).total_seconds() // 60))
    q, r = divmod(minutes, RESOLUTION_MINUTES)
    return (q + (1 if r else 0)) * RESOLUTION_MINUTES


def to_public_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        first, last, resolved = _parse(r["first_seen"]), _parse(r["last_seen"]), _parse(r.get("resolved_at"))
        if first is None or last is None:
            raise ValueError(f"archive row without first_seen/last_seen: {r}")
        out.append(
            {
                "station": r["station"],
                "elevator": r["elevator"],
                "description": " ".join(str(r["description"]).split()),
                "first_seen_utc": _iso(first),
                "last_seen_utc": _iso(last),
                "resolved_at_utc": _iso(resolved),
                "duration_minutes": duration_minutes(first, last),
                "status": "resolved" if resolved else "open",
            }
        )
    return out


def date_span(rows: list[dict[str, Any]]) -> tuple[str, str]:
    firsts = [r["first_seen_utc"] for r in rows if r["first_seen_utc"]]
    lasts = [r["last_seen_utc"] for r in rows if r["last_seen_utc"]]
    return (min(firsts)[:10], max(lasts)[:10]) if firsts and lasts else ("unknown", "unknown")


def readme_text(filename: str, n_rows: int, start: str, end: str) -> str:
    cols = "\n".join(f"- `{c}`: {COLUMN_NOTES[c]}" for c in COLUMNS)
    return (
        "# Public dataset: BART elevator outages\n\n"
        f"{ATTRIBUTION}\n\n"
        f"File: `{filename}` ({n_rows} outage intervals, {start} to {end}). One row per outage interval, "
        f"columns {', '.join(COLUMNS)}; timestamps are UTC at five-minute resolution, the poller's cadence.\n\n"
        f"Columns:\n{cols}\n\n"
        "No personal data: the dataset holds elevator outages only, never riders or trips.\n"
    )


def export(adapter: ArchiveAdapter, out_dir: Path = PUBLIC_DIR) -> dict[str, Any]:
    rows = to_public_rows(adapter.rows())
    start, end = date_span(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"bart_elevator_outages_{start}_{end}.csv"
    csv_path = out_dir / filename
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (out_dir / "README.md").write_text(readme_text(filename, len(rows), start, end))
    meta = {
        "file": filename,
        "rows": len(rows),
        "start": start,
        "end": end,
        "resolution_minutes": RESOLUTION_MINUTES,
        "attribution": ATTRIBUTION,
        "columns": COLUMNS,
        "archive": str(adapter.path),
    }
    (out_dir / f"{filename}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def build_fixture_archive(path: Path = FIXTURE_ARCHIVE, days: int = 3) -> Path:
    """A small synthetic archive in the fixture schema: a few outage intervals
    across three days, one still open, at five-minute snapshot cadence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    try:
        con.executescript(FIXTURE_SCHEMA)
        t0 = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
        snaps = [t0 + timedelta(minutes=5 * i) for i in range(days * 24 * 12)]
        con.executemany(
            "INSERT INTO snapshots (fetched_at, source) VALUES (?, ?)",
            [(s.isoformat(), "fixture") for s in snaps],
        )
        rows = [
            ("DELN", "DELN-E1", "DELN: Platform - Richmond", 0, 77, 78),
            ("PLZA", "PLZA-E2", "PLZA: Street to Concourse", 12, 300, 301),
            ("POWL", "POWL-E1", "POWL: Concourse - Platform (Millbrae)", 400, 466, 467),
            ("MCAR", "MCAR-E2", "MCAR: Street - Concourse (east)", 500, 540, 541),
            ("12TH", "12TH-E1", "12TH: Platform - Level 3", 700, len(snaps) - 1, None),
        ]
        con.executemany(
            "INSERT INTO outages (station, elevator, description, first_seen, last_seen, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (st, ev, desc, snaps[a].isoformat(), snaps[b].isoformat(), snaps[c].isoformat() if c else None)
                for st, ev, desc, a, b, c in rows
            ],
        )
        con.commit()
    finally:
        con.close()
    return path
