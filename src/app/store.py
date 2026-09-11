"""SQLite store for riders, trips, and the decisions inbox (``data/riders.sqlite``). Pure code."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from policy import Preferences, Trip

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "riders.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS riders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    preferences TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY,
    rider_id TEXT NOT NULL REFERENCES riders(id),
    origin TEXT NOT NULL,
    dest TEXT NOT NULL,
    days TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    needs TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY,
    rider_id TEXT NOT NULL,
    trip_id INTEGER NOT NULL,
    at TEXT NOT NULL,
    fragment TEXT NOT NULL,
    station TEXT,
    elevator TEXT,
    condition TEXT NOT NULL,
    affected TEXT NOT NULL,
    top_option TEXT,
    ranked_options TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    message TEXT,
    mechanisms TEXT NOT NULL,
    provider TEXT NOT NULL,
    source TEXT NOT NULL,
    sent INTEGER NOT NULL
);
"""

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RiderStore:
    def __init__(self, db_path: Path = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # --- riders ------------------------------------------------------------------------------
    def ensure_rider(self, rider_id: str, name: str | None = None, preferences: dict | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO riders (id, name, preferences, created_at) VALUES (?,?,?,?)",
                (rider_id, name or rider_id, json.dumps(preferences or {}), _now()),
            )

    def riders(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM riders ORDER BY created_at").fetchall()
        return [{**dict(r), "preferences": json.loads(r["preferences"])} for r in rows]

    # --- trips -------------------------------------------------------------------------------
    def add_trip(
        self,
        rider_id: str,
        origin: str,
        dest: str,
        days: list[str] | None = None,
        window: tuple[str, str] = ("00:00", "23:59"),
        needs: list[str] | None = None,
    ) -> int:
        self.ensure_rider(rider_id)
        days = [d for d in (days or list(WEEKDAYS)) if d in WEEKDAYS] or list(WEEKDAYS)
        needs = sorted(set(needs or ["elevator"]))
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO trips (rider_id, origin, dest, days, window_start, window_end, needs, "
                "created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    rider_id,
                    origin.upper(),
                    dest.upper(),
                    json.dumps(days),
                    window[0],
                    window[1],
                    json.dumps(needs),
                    _now(),
                ),
            )
        return int(cur.lastrowid)

    def trips(self, rider_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM trips" + (" WHERE rider_id=?" if rider_id else "") + " ORDER BY id"
        rows = self.conn.execute(sql, (rider_id,) if rider_id else ()).fetchall()
        return [{**dict(r), "days": json.loads(r["days"]), "needs": json.loads(r["needs"])} for r in rows]

    def as_policy_trip(self, row: dict[str, Any]) -> Trip:
        """The policy Trip for a stored trip, with the rider's preferences folded into its needs."""
        prefs = Preferences.from_dict(self.preferences(row["rider_id"]))
        return Trip(
            origin=row["origin"],
            dest=row["dest"],
            days=tuple(row["days"]),
            window=(row["window_start"], row["window_end"]),
            needs=frozenset(row["needs"]) | prefs.needs(),
            rider_id=row["rider_id"],
        )

    def preferences(self, rider_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT preferences FROM riders WHERE id=?", (rider_id,)).fetchone()
        return json.loads(row["preferences"]) if row else {}

    def set_preferences(self, rider_id: str, prefs: Preferences) -> None:
        self.ensure_rider(rider_id)
        with self.conn:
            payload = json.dumps(prefs.as_dict())
            self.conn.execute("UPDATE riders SET preferences=? WHERE id=?", (payload, rider_id))

    # --- inbox -------------------------------------------------------------------------------
    def add_decision(self, **fields: Any) -> int:
        cols = (
            "rider_id", "trip_id", "at", "fragment", "station", "elevator", "condition",
            "affected", "top_option", "ranked_options", "reasoning", "message", "mechanisms",
            "provider", "source", "sent",
        )  # fmt: skip
        values = [fields.get(c) for c in cols]
        for i, c in enumerate(cols):
            if c in ("ranked_options", "mechanisms") and not isinstance(values[i], str):
                values[i] = json.dumps(values[i] or [], default=str)
            if c == "affected":
                values[i] = "unknown" if values[i] is None else ("yes" if values[i] else "no")
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO inbox ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", values
            )
        return int(cur.lastrowid)

    def inbox(self, rider_id: str | None = None, *, until: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM inbox", []
        clauses = []
        if rider_id:
            clauses.append("rider_id=?")
            params.append(rider_id)
        if until:
            clauses.append("at<=?")
            params.append(until)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(sql + " ORDER BY at, id", params).fetchall()
        out = []
        for r in rows:
            row = dict(r)
            row["ranked_options"] = json.loads(r["ranked_options"])
            row["mechanisms"] = json.loads(r["mechanisms"])
            out.append(row)
        return out

    def clear_inbox(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM inbox")

    def seed_demo(self) -> None:
        """A demo rider with BART's two worked-example trips. Synthetic; labeled in the UI."""
        if self.trips("demo"):
            return
        self.ensure_rider("demo", "Demo rider (synthetic)", {"note": "synthetic demo rider"})
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        self.add_trip("demo", "SANL", "EMBR", days=weekdays, window=("07:30", "09:00"))
        self.add_trip("demo", "EMBR", "PLZA", days=weekdays, window=("17:00", "19:00"))
