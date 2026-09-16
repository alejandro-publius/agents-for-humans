"""Weekly quiet report: how little the agent interrupted a rider, against a BART-style alert count.

    python -m src.report --rider demo            # prints four numbers, writes results/interruptions.json

Reads data/outages.sqlite (what happened on the feed) and data/riders.sqlite (trips and the inbox).
The BART-style count assumes one alert per outage start and one per clearance at each station the
rider registered, which is how BART's per-station email and text alerts behave as documented on the
Elevator Status page ("Email and text alerts for stations of choice"). Nothing here calls a model.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from app.store import DEFAULT_DB as RIDERS_DB
from app.store import RiderStore
from src.poller import DEFAULT_DB as OUTAGES_DB

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS = REPO_ROOT / "results" / "interruptions.json"


def rider_report(store: RiderStore, outages_db: Path, rider_id: str) -> dict[str, Any]:
    trips = store.trips(rider_id)
    stations = sorted({t["origin"] for t in trips} | {t["dest"] for t in trips})
    conn = sqlite3.connect(outages_db) if outages_db.exists() else None
    outage_sql = "SELECT fragment, station_abbr, cleared_at FROM outages"
    outages = conn.execute(outage_sql).fetchall() if conn else []
    events = conn.execute("SELECT kind, fragment FROM events").fetchall() if conn else []
    station_of = {fragment: station for fragment, station, _ in outages}

    touched_stations = sorted({f for f, s, _ in outages if s in stations})
    inbox = store.inbox(rider_id)
    touched_trips = sorted({r["fragment"] for r in inbox if r["affected"] == "yes"})
    sent = [r for r in inbox if r["sent"]]
    bart_style = sum(1 for kind, fragment in events if station_of.get(fragment) in stations)

    days = _days_covered(conn)
    riders_total = max(1, len(store.riders()))
    rider_weeks = riders_total * days / 7 if days else 0.0
    return {
        "rider_id": rider_id,
        "days_covered": days,
        "interruptions_per_rider_week": round(len(sent) / rider_weeks, 2) if rider_weeks else None,
        "registered_trips": len(trips),
        "registered_stations": stations,
        "outages_on_feed": len(outages),
        "outages_touching_your_stations": len(touched_stations),
        "outages_touching_your_trips": len(touched_trips),
        "interruptions_sent": len(sent),
        "bart_style_station_alerts": bart_style,
        "quiet_decisions": len(inbox) - len(sent),
        "assumption": (
            "BART-style alerts = one per outage start plus one per clearance at each registered station"
        ),
    }


def _days_covered(conn: sqlite3.Connection | None) -> float:
    """Days spanned by the snapshots in the outage db, from first poll to last, as a fraction."""
    if conn is None:
        return 0.0
    row = conn.execute("SELECT MIN(taken_at), MAX(taken_at) FROM snapshots").fetchone()
    if not row or not row[0]:
        return 0.0
    from datetime import datetime

    first, last = datetime.fromisoformat(row[0]), datetime.fromisoformat(row[1])
    return round(max((last - first).total_seconds(), 0) / 86400, 4)


def quiet_metric(store: RiderStore, outages_db: Path, source: str) -> dict[str, Any]:
    """Interrupts per rider-week across every rider in the store, for results/quiet.json."""
    riders = [r["id"] for r in store.riders()]
    conn = sqlite3.connect(outages_db) if outages_db.exists() else None
    days = _days_covered(conn)
    inbox = store.inbox()
    sent = sum(1 for r in inbox if r["sent"])
    rider_weeks = len(riders) * days / 7 if days else 0.0
    return {
        "source": source,
        "riders": len(riders),
        "days_covered": days,
        "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] if conn else 0,
        "decisions": len(inbox),
        "interruptions": sent,
        "rider_weeks": round(rider_weeks, 4),
        "interruptions_per_rider_week": round(sent / rider_weeks, 2) if rider_weeks else None,
        "note": (
            "interruptions = inbox rows sent to a rider (messages and decision cards); rider-weeks = "
            "riders x days covered by the snapshots / 7. A synthetic archive spanning minutes gives a "
            "large per-week rate; the archive entry is the one that matters once the poller has run."
        ),
    }


def write_quiet(
    store: RiderStore, outages_db: Path, out: Path = REPO_ROOT / "results" / "quiet.json"
) -> dict:
    entries = {
        "synthetic_replay": quiet_metric(
            store, outages_db, "make replay on fixtures/bart/archive_synthetic.json"
        )
    }
    archive_manifest = REPO_ROOT / "data" / "archive" / "manifest.json"
    archive_db = REPO_ROOT / "data" / "archive" / "outages.sqlite"
    if archive_manifest.exists() and archive_db.exists():
        entries["archive"] = quiet_metric(store, archive_db, "live archive (data/archive), same riders")
    else:
        entries["archive"] = {"status": "awaiting archive", "note": "make archive has not recorded data yet"}
    out.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--rider", default="demo")
    parser.add_argument("--db", type=Path, default=RIDERS_DB)
    parser.add_argument("--outages-db", type=Path, default=OUTAGES_DB)
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args(argv)

    store = RiderStore(args.db)
    riders = [r["id"] for r in store.riders()]
    if args.rider not in riders:
        print(f"report: rider {args.rider!r} not found; known riders: {riders}", file=sys.stderr)
        return 2
    reports = {rid: rider_report(store, args.outages_db, rid) for rid in riders}
    me = reports[args.rider]
    quiet = write_quiet(store, args.outages_db)
    q = quiet["synthetic_replay"]
    print(f"{q['days_covered']} days, {q['interruptions']} interruptions, {q['decisions']} decisions")
    print(
        f"{me['outages_touching_your_stations']} outages touched your stations, "
        f"{me['outages_touching_your_trips']} touched your trips, "
        f"{me['interruptions_sent']} interruptions sent; "
        f"BART-style station alerts would have sent {me['bart_style_station_alerts']}."
    )
    payload = {
        "provider_note": "inbox produced by make replay on the mock provider from a synthetic archive",
        "source": {"riders_db": str(args.db), "outages_db": str(args.outages_db)},
        "rider": me,
        "all_riders": reports,
    }
    args.out.parent.mkdir(exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
