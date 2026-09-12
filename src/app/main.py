"""One-page rider app. ``make app`` serves it on http://127.0.0.1:8000.

Register a trip, read the inbox of every decision (reasoning and BART's option ranking shown),
and scrub the replay timeline. Everything is read from ``data/riders.sqlite`` and
``data/outages.sqlite``; nothing here calls a model or the network.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.replay import answer_pending
from app.store import DEFAULT_DB, WEEKDAYS, RiderStore
from kb.load import load_stations
from src.poller import DEFAULT_DB as OUTAGES_DB

app = FastAPI(title="Last Elevator", docs_url=None, redoc_url=None)
_store: RiderStore | None = None
_paths = {"riders": DEFAULT_DB, "outages": OUTAGES_DB}


def configure(riders_db: Path = DEFAULT_DB, outages_db: Path = OUTAGES_DB) -> None:
    global _store
    _paths["riders"], _paths["outages"] = Path(riders_db), Path(outages_db)
    _store = RiderStore(_paths["riders"])


def store() -> RiderStore:
    global _store
    if _store is None:
        _store = RiderStore(_paths["riders"])
    return _store


def timeline() -> list[dict[str, Any]]:
    """Snapshots in order with the outages active after each one, reconstructed from events."""
    if not _paths["outages"].exists():
        return []
    conn = sqlite3.connect(_paths["outages"])
    snaps = conn.execute("SELECT DISTINCT taken_at, source FROM snapshots ORDER BY taken_at").fetchall()
    events = conn.execute("SELECT at, kind, fragment FROM events ORDER BY id").fetchall()
    out, active = [], set()
    for taken_at, source in snaps:
        for at, kind, fragment in events:
            if at == taken_at:
                (active.add if kind == "new" else active.discard)(fragment)
        out.append({"at": taken_at, "source": source, "active": sorted(active)})
    return out


@app.get("/api/status")
def api_status() -> JSONResponse:
    s = store()
    return JSONResponse(
        {
            "riders": len(s.riders()),
            "trips": len(s.trips()),
            "inbox": len(s.inbox()),
            "sent": sum(r["sent"] for r in s.inbox()),
            "snapshots": len(timeline()),
            "stations_in_kb": len(load_stations()),
            "riders_db": str(_paths["riders"]),
            "outages_db": str(_paths["outages"]),
        }
    )


@app.get("/api/trips")
def api_trips() -> JSONResponse:
    return JSONResponse(store().trips())


@app.get("/api/inbox")
def api_inbox(rider: str | None = None, until: str | None = None) -> JSONResponse:
    return JSONResponse(store().inbox(rider, until=until))


@app.get("/api/timeline")
def api_timeline() -> JSONResponse:
    return JSONResponse(timeline())


@app.post("/trips")
def post_trip(
    rider_id: str = Form("demo"),
    origin: str = Form(...),
    dest: str = Form(...),
    days: list[str] | None = Form(None),
    window_start: str = Form("00:00"),
    window_end: str = Form("23:59"),
    needs: str = Form("elevator"),
):
    stations = load_stations()
    if origin.upper() not in stations or dest.upper() not in stations:
        error = {"error": "origin and dest must be BART station abbreviations in the KB"}
        return JSONResponse(error, status_code=400)
    needs_list = [n.strip() for n in needs.split(",") if n.strip()]
    window = (window_start, window_end)
    store().add_trip(rider_id.strip() or "demo", origin, dest, days or list(WEEKDAYS), window, needs_list)
    return RedirectResponse("/", status_code=303)


STATIC = Path(__file__).resolve().parent / "static"


@app.post("/decisions/{row_id}")
def post_decision(row_id: int, answer: str = Form(...)):
    """The rider answers a decision card; the paused run resumes from its persisted session."""
    try:
        sessions = _paths["riders"].parent / "sessions"
        result = answer_pending(store(), row_id, answer, sessions_dir=sessions)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text())
