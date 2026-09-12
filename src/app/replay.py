"""Populate the inbox from an archived elevator feed, offline.

    python -m src.app.replay                       # synthetic archive (fixtures/bart/archive_synthetic.json)
    python -m src.app.replay --archive data/archive/manifest.json   # a real archive recorded by the poller

For every snapshot, in order: run the poller diff, then for every *new* outage and every registered
trip run the policy engine (code). Trips the outage does not touch get a quiet inbox row (sent=0).
Affected trips run the agent (mock model that echoes the policy engine unless Bedrock credentials
are present) and get a message row (sent=1). Every row keeps the reasoning and the ranked options.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.core import AgentConfig
from agent.decision_card import case_key
from agent.mock_model import MockModel
from agent.outage_parser import parse_and_validate
from agent.run import reopen_paused_run, resume_run, run_with_decision
from app.store import DEFAULT_DB, RiderStore
from bart import BartClient
from policy import Decision, Outage, assess
from policy.sun import PACIFIC
from src.poller import DEFAULT_DB as OUTAGES_DB
from src.poller import connect, poll_once

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_ARCHIVE = REPO_ROOT / "fixtures" / "bart" / "archive_synthetic.json"


SESSIONS_DIR = REPO_ROOT / "data" / "sessions"


def session_id_for(rider_id: str, trip_id: int, key: str) -> str:
    import hashlib

    return f"{rider_id}-{trip_id}-{hashlib.sha1(key.encode()).hexdigest()[:10]}"


def echo_model(decision: Decision, station: str, elevator: str, *, resume: bool = False) -> MockModel:
    """Offline stand-in: a scripted model that drafts the policy engine's top option using BART's text.
    With resume=True only the Plan turn is scripted (the draft happened before the pause)."""
    top = decision.top_option or "mitigation_trip"
    documented = decision.documented_option or {}
    steps = [documented.get("text") or "Contact the Station Agent for assistance."]
    minutes = next((o.added_minutes for o in decision.ranked_options if o.option == top), None)
    message = f"{steps[0]} ({top.replace('_', ' ')})"
    draft = {
        "type": "tool_use",
        "name": "draft_message",
        "input": {
            "option": top,
            "station_abbr": station,
            "elevator": elevator,
            "steps": steps,
            "added_minutes": minutes,
        },
    }
    plan = {
        "type": "tool_use",
        "name": "Plan",
        "input": {
            "affected": bool(decision.affected),
            "option": top,
            "steps": steps,
            "added_minutes": minutes,
            "needs_human_decision": top == "mitigation_trip",
            "message": message,
        },
    }
    return MockModel([plan] if resume else [draft, plan], name="echo-policy")


def live_model_or_none():
    if os.getenv("AWS_REGION") and (os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_BEARER_TOKEN_BEDROCK")):
        from strands.models import BedrockModel

        return BedrockModel(region_name=os.environ["AWS_REGION"])
    return None


def load_archive(manifest: Path) -> list[dict[str, Any]]:
    data = json.loads(manifest.read_text())
    base = manifest.parent
    return [
        {"at": s["at"], "path": (base / s["file"]).resolve(), "note": s.get("note", "")}
        for s in data["snapshots"]
    ]


def replay(
    store: RiderStore,
    outages_conn,
    manifest: Path = SYNTHETIC_ARCHIVE,
    *,
    provider_model=None,
    sessions_dir: Path | None = None,
) -> dict[str, Any]:
    client = BartClient(api_key=None)
    provider = "mock" if provider_model is None else "bedrock"
    stats = {"snapshots": 0, "new_outages": 0, "decisions": 0, "sent": 0, "pending": 0, "provider": provider}
    sessions_dir = Path(sessions_dir) if sessions_dir else SESSIONS_DIR
    source = f"archive:{manifest.name}"
    trips = store.trips()
    for snap in load_archive(manifest):
        at = datetime.fromisoformat(snap["at"])
        result = poll_once(client, outages_conn, fixture=snap["path"], now=at)
        stats["snapshots"] += 1
        sql = "SELECT fragment FROM events WHERE kind='new' AND at=?"
        rows = outages_conn.execute(sql, (result.taken_at,))
        new_fragments = [r[0] for r in rows]
        for fragment in new_fragments:
            stats["new_outages"] += 1
            parsed = parse_and_validate(fragment)
            for row in trips:
                trip = store.as_policy_trip(row)
                pending: dict[str, Any] = {}
                if not parsed.valid:
                    decision = None
                    reasoning = "; ".join(parsed.problems)
                    condition, affected, top = "unparsed", None, None
                    ranked, mechanisms, message = [], {}, None
                else:
                    when = at.astimezone(PACIFIC)
                    outage = Outage(parsed.station_abbr, parsed.kb_elevator, fragment)
                    decision = assess(trip, outage, when, client)
                    condition, affected, top = decision.condition, decision.affected, decision.top_option
                    ranked = [o.__dict__ for o in decision.ranked_options]
                    default_reason = f"{condition}: BART option ranked in policy order"
                    reasoning = "; ".join(decision.notes) or default_reason
                    mechanisms, message = {}, None
                    if affected is not False and decision.top_option:
                        echo = echo_model(decision, parsed.station_abbr, parsed.kb_elevator)
                        model = provider_model or echo
                        key = case_key(decision.station, decision.elevator, decision.condition)
                        cfg = AgentConfig(
                            decisions=store.decisions(row["rider_id"]),
                            session_id=session_id_for(row["rider_id"], row["id"], key),
                            session_dir=str(sessions_dir),
                        )
                        report = run_with_decision(
                            trip, fragment, parsed.as_label(), decision, when, model, config=cfg
                        )
                        mechanisms = report.mechanisms
                        message = (report.final_plan or {}).get("message")
                        if report.error:
                            reasoning += f"; agent error: {report.error}"
                        if report.paused:
                            pending = {
                                "condition": "pending_decision",
                                "card": report.card,
                                "session_id": cfg.session_id,
                                "interrupt_id": report.interrupt["id"],
                            }
                            reasoning = "paused for a rider decision: " + ", ".join(report.card["flags"])
                            stats["pending"] += 1
                sent = int(affected is not False and top is not None and message is not None)
                store.add_decision(
                    rider_id=row["rider_id"],
                    trip_id=row["id"],
                    at=result.taken_at,
                    fragment=fragment,
                    station=parsed.station_abbr,
                    elevator=parsed.kb_elevator,
                    condition=pending.get("condition", condition),
                    affected=affected,
                    top_option=top,
                    ranked_options=ranked,
                    reasoning=reasoning,
                    message=message,
                    mechanisms=mechanisms,
                    provider=stats["provider"],
                    source=source,
                    sent=sent or int(bool(pending)),
                    session_id=pending.get("session_id"),
                    card=pending.get("card"),
                    interrupt_id=pending.get("interrupt_id"),
                )
                stats["decisions"] += 1
                stats["sent"] += sent
    return stats


def answer_pending(
    store: RiderStore, row_id: int, answer: str, *, provider_model=None, sessions_dir: Path | None = None
) -> dict[str, Any]:
    """The rider answers a decision card: reopen the persisted session, resume, store the answer."""
    row = store.inbox_row(row_id)
    if row is None or row["condition"] != "pending_decision" or not row["session_id"]:
        raise ValueError(f"inbox row {row_id} is not a pending decision")
    if answer not in ("accept", "decline"):
        raise ValueError("answer must be 'accept' or 'decline'")
    trip_row = next(t for t in store.trips(row["rider_id"]) if t["id"] == row["trip_id"])
    trip = store.as_policy_trip(trip_row)
    when = datetime.fromisoformat(row["at"]).astimezone(PACIFIC)
    parsed = parse_and_validate(row["fragment"])
    outage = Outage(parsed.station_abbr, parsed.kb_elevator, row["fragment"])
    decision = assess(trip, outage, when, BartClient())
    cfg = AgentConfig(
        decisions=store.decisions(row["rider_id"]),
        session_id=row["session_id"],
        session_dir=str(Path(sessions_dir) if sessions_dir else SESSIONS_DIR),
    )
    model = provider_model or echo_model(decision, parsed.station_abbr, parsed.kb_elevator, resume=True)
    report = reopen_paused_run(
        trip, row["fragment"], parsed.as_label(), decision, row["interrupt_id"], model, config=cfg
    )
    resumed = resume_run(report, answer)
    key = case_key(decision.station, decision.elevator, decision.condition)
    store.remember_decision(row["rider_id"], key, answer)
    message = (resumed.final_plan or {}).get("message")
    store.answer_decision(row_id, answer, message, decision.condition if message else "pending_decision")
    return {"row_id": row_id, "answer": answer, "message": message, "error": resumed.error}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--archive", type=Path, default=SYNTHETIC_ARCHIVE)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--outages-db", type=Path, default=OUTAGES_DB)
    parser.add_argument("--reset", action="store_true", help="clear the inbox and the outages db first")
    parser.add_argument("--seed-demo", action="store_true", help="add the demo rider and trips if absent")
    args = parser.parse_args(argv)

    if args.reset:
        args.outages_db.unlink(missing_ok=True)
    store = RiderStore(args.db)
    if args.reset:
        store.clear_inbox()
    if args.seed_demo:
        store.seed_demo()
    conn = connect(args.outages_db)
    stats = replay(store, conn, args.archive, provider_model=live_model_or_none())
    print(
        f"inbox replay: {stats['snapshots']} snapshots, {stats['new_outages']} new outages, "
        f"{stats['decisions']} decisions, {stats['sent']} messages sent, {stats['pending']} pending "
        f"decisions (provider={stats['provider']}, "
        f"archive={args.archive.name}, db={args.db})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
