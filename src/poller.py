"""Poll BART's elevator feed, diff against the last snapshot, record new and cleared outages.

    python -m src.poller --once --fixture fixtures/bart/elev_sample.json   # offline, one poll
    python -m src.poller --interval 300                                     # live, needs BART_API_KEY

Live polling needs ``BART_API_KEY``; without it and without ``--fixture`` the poller exits with a
message. A failed live call logs one line and the loop waits for the next tick. Parsing is code:
``bart.outage_fragments`` splits the advisory, the regex parser plus KB validation resolves the
station and elevator (no model call in the poller).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent.outage_parser import parse_and_validate
from bart import BartClient, BartUnavailable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "outages.sqlite"
log = logging.getLogger("poller")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    taken_at TEXT NOT NULL,
    source TEXT NOT NULL,
    advisory_id TEXT,
    description TEXT,
    fragment_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY,
    fragment TEXT NOT NULL,
    station_abbr TEXT,
    kb_elevator TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    cleared_at TEXT,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outages_active ON outages (fragment) WHERE cleared_at IS NULL;
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    fragment TEXT NOT NULL,
    outage_id INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class PollResult:
    taken_at: str
    source: str
    fragments: tuple[str, ...]
    inserted: int
    cleared: int
    unchanged: int


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def poll_once(
    client: BartClient,
    conn: sqlite3.Connection,
    *,
    fixture: Path | None = None,
    now: datetime | None = None,
) -> PollResult:
    """Fetch the feed once and apply the diff. Raises BartUnavailable on a failed live call."""
    now = now or datetime.now(UTC)
    taken_at = now.isoformat(timespec="seconds")
    source = f"fixture:{fixture.name}" if fixture else client.mode
    advisories = client.elevator_advisories(fixture=fixture)
    fragments = tuple(dict.fromkeys(f for adv in advisories for f in adv.fragments))

    with conn:
        for adv in advisories:
            conn.execute(
                "INSERT INTO snapshots (taken_at, source, advisory_id, description, fragment_count) "
                "VALUES (?,?,?,?,?)",
                (taken_at, source, adv.id, adv.description, len(adv.fragments)),
            )
        rows = conn.execute("SELECT id, fragment FROM outages WHERE cleared_at IS NULL")
        active = {fragment: outage_id for outage_id, fragment in rows}

        inserted = cleared = unchanged = 0
        for fragment in fragments:
            if fragment in active:
                conn.execute("UPDATE outages SET last_seen=? WHERE id=?", (taken_at, active[fragment]))
                unchanged += 1
                continue
            parsed = parse_and_validate(fragment)
            cur = conn.execute(
                "INSERT INTO outages (fragment, station_abbr, kb_elevator, first_seen, last_seen, source) "
                "VALUES (?,?,?,?,?,?)",
                (fragment, parsed.station_abbr, parsed.kb_elevator, taken_at, taken_at, source),
            )
            conn.execute(
                "INSERT INTO events (at, kind, fragment, outage_id) VALUES (?,?,?,?)",
                (taken_at, "new", fragment, cur.lastrowid),
            )
            inserted += 1
        for fragment, outage_id in active.items():
            if fragment not in fragments:
                conn.execute("UPDATE outages SET cleared_at=? WHERE id=?", (taken_at, outage_id))
                conn.execute(
                    "INSERT INTO events (at, kind, fragment, outage_id) VALUES (?,?,?,?)",
                    (taken_at, "cleared", fragment, outage_id),
                )
                cleared += 1
    return PollResult(taken_at, source, fragments, inserted, cleared, unchanged)


def archive_payload(archive_dir: Path, payload: dict, taken_at: str, source: str) -> Path:
    """Save one raw feed payload and append it to ``manifest.json`` in the replay format."""
    import json

    archive_dir.mkdir(parents=True, exist_ok=True)
    name = f"elev_{taken_at.replace(':', '').replace('+', 'p')}.json"
    (archive_dir / name).write_text(json.dumps(payload, indent=1) + "\n")
    manifest = archive_dir / "manifest.json"
    data = json.loads(manifest.read_text()) if manifest.exists() else {"snapshots": []}
    data["snapshots"].append({"at": taken_at, "file": name, "note": source})
    manifest.write_text(json.dumps(data, indent=1) + "\n")
    return archive_dir / name


def active_outages(conn: sqlite3.Connection) -> list[dict[str, str | None]]:
    rows = conn.execute(
        "SELECT fragment, station_abbr, kb_elevator, first_seen, last_seen FROM outages "
        "WHERE cleared_at IS NULL ORDER BY first_seen, id"
    ).fetchall()
    keys = ("fragment", "station_abbr", "kb_elevator", "first_seen", "last_seen")
    return [dict(zip(keys, r, strict=True)) for r in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--once", action="store_true", help="poll one time and exit")
    parser.add_argument("--fixture", type=Path, help="read this fixture instead of the live feed")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite path (default {DEFAULT_DB})")
    parser.add_argument("--interval", type=int, default=300, help="seconds between polls (default 300)")
    parser.add_argument(
        "--archive-dir", type=Path, help="also save every raw payload here plus manifest.json (replayable)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    client = BartClient()
    if not args.fixture and not client.live:
        msg = "poller: no BART_API_KEY; pass --fixture fixtures/bart/<file>.json to run offline"
        print(msg, file=sys.stderr)
        return 2
    conn = connect(args.db)
    while True:
        try:
            r = poll_once(client, conn, fixture=args.fixture)
            if args.archive_dir:
                payload = client.elevators(fixture=args.fixture)
                archive_payload(args.archive_dir, payload, r.taken_at, r.source)
            print(
                f"poll {r.taken_at} source={r.source} fragments={len(r.fragments)} "
                f"inserted={r.inserted} cleared={r.cleared} unchanged={r.unchanged} db={args.db}"
            )
        except BartUnavailable as exc:
            log.warning("poll skipped: %s", exc)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
