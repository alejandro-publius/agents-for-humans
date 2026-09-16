"""Export ``evals/labels/relevance.csv``: one row per (outage, demo trip) decision, two label columns.

    python scripts/export_labels.py            # merges new inbox rows into the CSV, keeps existing labels

Two people fill ``label_1`` and ``label_2`` independently with ``relevant`` or ``not`` (was this
outage worth interrupting this rider for?). ``evals/relevance.py`` scores the agent against them.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from app.store import DEFAULT_DB, RiderStore  # noqa: E402

CSV_PATH = REPO_ROOT / "evals" / "labels" / "relevance.csv"
FIELDS = [
    "key", "at", "rider_id", "trip_id", "trip", "outage_fragment", "station", "elevator", "condition",
    "agent_affected", "agent_sent", "top_option", "source", "label_1", "label_2",
]  # fmt: skip


def export(db: Path = DEFAULT_DB, csv_path: Path = CSV_PATH) -> tuple[int, int]:
    """Merge inbox rows into the CSV by key. Returns (rows_total, rows_added)."""
    existing: dict[str, dict[str, str]] = {}
    if csv_path.exists():
        with csv_path.open(newline="") as fh:
            existing = {row["key"]: row for row in csv.DictReader(fh)}
    store = RiderStore(db)
    trips = {t["id"]: t for t in store.trips()}
    added = 0
    for r in store.inbox():
        key = f"{r['at']}|{r['rider_id']}|{r['trip_id']}|{r['fragment']}"
        if key in existing:
            continue
        trip = trips.get(r["trip_id"], {})
        existing[key] = {
            "key": key,
            "at": r["at"],
            "rider_id": r["rider_id"],
            "trip_id": str(r["trip_id"]),
            "trip": f"{trip.get('origin', '?')}->{trip.get('dest', '?')}",
            "outage_fragment": r["fragment"],
            "station": r["station"] or "",
            "elevator": r["elevator"] or "",
            "condition": r["condition"],
            "agent_affected": r["affected"],
            "agent_sent": str(r["sent"]),
            "top_option": r["top_option"] or "",
            "source": r["source"],
            "label_1": "",
            "label_2": "",
        }
        added += 1
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda x: (x["at"], x["rider_id"], x["trip_id"], x["key"])):
            writer.writerow({k: row.get(k, "") for k in FIELDS})
    return len(existing), added


def main() -> int:
    total, added = export()
    shown = CSV_PATH.relative_to(REPO_ROOT)
    print(f"labels: {shown} has {total} rows ({added} added); label_1/label_2 await two humans")
    return 0


if __name__ == "__main__":
    sys.exit(main())
