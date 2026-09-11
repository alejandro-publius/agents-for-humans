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

    return {
        "rider_id": rider_id,
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
