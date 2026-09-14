"""AgentCore Runtime entrypoint for Last Elevator (the "about five lines" rung).

    from bedrock_agentcore.runtime import BedrockAgentCoreApp
    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload, context=None):
        return handle(payload)

    app.run()

Payload contract (JSON in, JSON out), the same shape the poller and the app
use locally:

    in:  {"rider_id": "r1", "origin": "DELN", "destination": "EMBR",
          "outages": ["DELN-E1"], "via": [], "after_dark": false, "last_train": false,
          "answer": null | true | false,      # an answer resumes a paused run
          "note": "no ramps today, pushing a stroller"}   # optional: the rider's own words, read into constraints
         or {"prompt": "<the payload as JSON text, or a sentence naming the elevator that is out>"}
         (what the evaluation runner and `agentcore invoke` send)
    out: {"state": "quiet" | "sent" | "held" | "pending" | "withdrawn" | "already_sent" | "invalid",
          "session_reset": true | false (on quiet: the trip's conversation was deleted with its outage),
          "composed_by": "model" | "code" | "none" (on sent, held and pending),
          "withdrawn": [case keys closed: the elevator is back, or the question was superseded by daytime],
          "forgotten": [case keys whose decision was dropped because the elevator is back],
          "note": {"constraints": [what the note ruled out], "read_by": "model" | "none" | "failed: ..."},
          "plan": {...} | null, "card": {...} | null, "gate_counts": {...},
          "memory": {"status": "ok" | "degraded" | "none", "reason", "backlog", "replayed"}}

`handle` is pure Python over the package's agent stack and is tested
offline with the scripted model; the Bedrock model and the session manager
are injected by `make_runtime()` on the laptop. Deployment: `make
agentcore-deploy` (dry run) prints the toolkit steps and the IAM list.

Sessions: the pause (`pending`) and the answer must reach the same runtime
session, so the caller invokes with one stable runtimeSessionId per rider
(`le_dispatch.interfaces.runtime_session_id(rider_id)`: the API requires
at least 33 characters) and polls more often than the runtime's idle
limit while a question is open. The files under LAST_ELEVATOR_DATA are that session's copy; the
poller and the app keep the durable ones (INTEGRATION.md 6b). With LAST_ELEVATOR_MEMORY_ID set, every
decision is also written to AgentCore Memory (one actor per rider) and read from it when a session does
not know the case, so "never asked twice" holds across runtime sessions (`make agentcore-memory`).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from le_dispatch import live, tracing  # noqa: E402
from le_dispatch.interfaces import Trip, fixture_policy  # noqa: E402
from le_dispatch.interrupts import DecisionMemory, Inbox, SentLog, build_decision_run  # noqa: E402
from le_dispatch.note import constrained, read_note  # noqa: E402

DATA_DIR = Path(os.environ.get("LAST_ELEVATOR_DATA", "/tmp/last-elevator"))
MEMORY_ID_ENV = "LAST_ELEVATOR_MEMORY_ID"  # set: the rider's decisions also go to AgentCore Memory


def decision_store_factory(
    memory_id: str | None = None, region: str | None = None, client: Any = None
) -> Callable[[Trip], Any] | None:
    """The three stores per rider (the actor), when LAST_ELEVATOR_MEMORY_ID names a Memory; else None and the
    decisions live in the session and the mirror only. One client per container, built on first use and
    wrapped in ResilientMemoryClient, so a Memory outage degrades the durable copy (the invocation still
    delivers from the session's copy) and a write that failed is replayed on a later invocation."""
    memory_id = memory_id or os.environ.get(MEMORY_ID_ENV)
    if not memory_id:
        return None
    region = region or os.environ.get("AWS_REGION", "us-west-2")
    shared: dict[str, Any] = {"client": client}

    def make(trip: Trip) -> Any:
        from le_dispatch.agentcore_memory import (
            AgentCoreCardStore,
            AgentCoreDecisionStore,
            AgentCoreSentStore,
            ResilientMemoryClient,
        )

        if shared["client"] is None:
            import boto3

            shared["client"] = boto3.client("bedrock-agentcore", region_name=region)
        if not isinstance(shared["client"], ResilientMemoryClient):
            shared["client"] = ResilientMemoryClient(shared["client"])
        resilient = shared["client"]
        return MemoryStores(
            AgentCoreDecisionStore(resilient, memory_id, trip.rider_id),
            AgentCoreSentStore(resilient, memory_id, trip.rider_id),
            AgentCoreCardStore(resilient, memory_id, trip.rider_id),
        )

    return make


class MemoryStores:
    """The durable copies for one rider: the decisions, what was delivered, and the open questions."""

    def __init__(self, decisions: Any, sent: Any, cards: Any = None):
        self.decisions = decisions
        self.sent = sent
        self.cards = cards

    def status(self) -> dict[str, Any]:
        from le_dispatch.agentcore_memory import memory_status

        return memory_status(self.decisions, self.sent, self.cards)


class InvalidPayload(ValueError):
    pass


PROMPT_ELEVATOR = re.compile(r"\b(?i:elevator) ([A-Z0-9]{4}-E\d+) (?i:at) ([A-Z0-9]{4})\b")
PROMPT_TRIP = re.compile(r"\b(?i:from) ([A-Z0-9]{4}) (?i:to) ([A-Z0-9]{4})\b")


def payload_from_prompt(prompt: str) -> dict[str, Any]:
    """A {"prompt": text} invocation (the shape the evaluation runner and `agentcore invoke` send): the text
    may start with the payload as a JSON object (the exported dataset does), or be a sentence naming the
    elevator that is out ("elevator DELN-E1 at DELN is out", optionally "from DELN to EMBR", "after
    dark", "last train")."""
    text = prompt.strip()
    if text.startswith("{"):
        depth = 0
        for k, ch in enumerate(text):
            depth += ch == "{"
            depth -= ch == "}"
            if depth == 0:
                try:
                    obj = json.loads(text[: k + 1])
                except ValueError:
                    break
                if isinstance(obj, dict):
                    return obj
                break
    m = PROMPT_ELEVATOR.search(text)
    if not m:
        raise InvalidPayload("prompt must carry the payload as JSON or name the elevator that is out")
    elevator, station = m.group(1), m.group(2)
    trip = PROMPT_TRIP.search(text)
    origin = trip.group(1) if trip else station
    destination = trip.group(2) if trip else ("EMBR" if station != "EMBR" else "MONT")
    low = text.lower()
    return {
        "rider_id": "prompt",
        "origin": origin,
        "destination": destination,
        "outages": [elevator],
        "after_dark": "after dark" in low,
        "last_train": "last train" in low,
    }


def trip_from(payload: Any) -> Trip:
    """The trip in the payload, or InvalidPayload with a reason the app can show. Nothing runs on a bad
    payload: no model, no file, no state change."""
    if isinstance(payload, dict) and "rider_id" not in payload and isinstance(payload.get("prompt"), str):
        payload = payload_from_prompt(payload["prompt"])
    if not isinstance(payload, dict):
        raise InvalidPayload("payload must be a JSON object")
    for key in ("rider_id", "origin", "destination"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InvalidPayload(f"{key} must be a non-empty string")
    for key in ("outages", "via"):
        value = payload.get(key, [])
        if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) and v for v in value):
            raise InvalidPayload(f"{key} must be a list of non-empty strings")
    for key in ("after_dark", "last_train"):
        if key in payload and not isinstance(payload[key], bool):
            raise InvalidPayload(f"{key} must be true or false")
    if "answer" in payload and payload["answer"] is not None and not isinstance(payload["answer"], bool):
        raise InvalidPayload("answer must be true, false or null")
    if "note" in payload and payload["note"] is not None and not isinstance(payload["note"], str):
        raise InvalidPayload("note must be a string or null")
    return Trip(
        rider_id=payload["rider_id"].strip(),
        origin=payload["origin"].strip(),
        destination=payload["destination"].strip(),
        outages=tuple(payload.get("outages", ())),
        via=tuple(payload.get("via", ())),
        after_dark=bool(payload.get("after_dark", False)),
        last_train=bool(payload.get("last_train", False)),
    )


def handle(
    payload: dict[str, Any],
    *,
    model_factory: Callable[[Trip, Any], Any],
    kb: Any = None,
    policy: Any = None,
    session_manager_factory: Callable[[Trip], Any] | None = None,
    data_dir: Path = DATA_DIR,
    decision_store_factory: Callable[[Trip], Any] | None = None,
    retry_strategy: Any = None,
) -> dict[str, Any]:
    """One invocation: decide, run the gated agent, pause or deliver. decision_store_factory: per rider, the
    durable copies in AgentCore Memory (a MemoryStores pair: the decisions the memory writes through to
    and reads from, and the sent log's), or a bare decision store. retry_strategy: Strands' throttle
    strategy for the run (`make_runtime` sets the live one, le_dispatch/live.py; None keeps the SDK's)."""
    if kb is None or policy is None:
        kb, policy = fixture_policy()  # the laptop injects the real KB and policy engine
    try:
        trip = trip_from(payload)
    except InvalidPayload as exc:
        return {"state": "invalid", "reason": str(exc), "plan": None, "card": None, "gate_counts": {}, "withdrawn": []}
    decision = policy(trip)
    note_out = {"constraints": [], "read_by": "none"}
    if (payload.get("note") or "").strip() and decision.affected:
        # the rider's own words: the model reads them into a fixed vocabulary, code applies it as feasibility
        kinds, how = read_note(model_factory(trip, decision), payload["note"])
        note_out = {"constraints": kinds, "read_by": how}
        if kinds:
            policy = constrained(policy, kinds)
            decision = policy(trip)
            note_out["set_aside"] = decision.note_set_aside
    stores = decision_store_factory(trip) if decision_store_factory else None
    memory_state = stores.status if isinstance(stores, MemoryStores) else (lambda: {"status": "none"})
    inbox = Inbox(data_dir / "inbox.json", store=getattr(stores, "cards", None))
    sent = SentLog(data_dir / f"{trip.rider_id}-sent.json", store=getattr(stores, "sent", None))
    withdrawn = inbox.withdraw_stale(trip)  # an open question whose elevator is back is closed, never re-asked
    sent.clear_stale(trip)  # and a plan sent for an outage that ended may be sent again for the next one
    decisions = getattr(stores, "decisions", stores)  # a MemoryStores pair, or a bare decision store
    memory = DecisionMemory(data_dir / f"{trip.rider_id}-decisions.json", store=decisions)
    forgotten = memory.clear_stale(trip)  # a decision belongs to its outage: the next outage asks afresh
    make_session = session_manager_factory or default_session_manager(data_dir)
    if not decision.affected:
        # the conversation belongs to its outage too: with nothing out on the trip, the session that carried
        # the outage's messages, tool results and paused interrupt is deleted; the next outage starts clean
        return {
            "state": "quiet",
            "plan": None,
            "card": None,
            "gate_counts": {},
            "withdrawn": withdrawn,
            "forgotten": forgotten,
            "session_reset": reset_session(make_session, trip),
            "memory": memory_state(),
        }
    already = sent.get(trip.case_key)
    if already is not None:
        # one outage, one message: the rider was told; the next poll runs no model and sends nothing new,
        # and an answer that arrives after the delivery (a double tap, a changed mind, a late answer to a
        # question the morning superseded) is answered with what was delivered, never with a failure
        return {
            "state": "already_sent",
            "delivered_state": already["state"],  # sent, or held (the rider declined this reroute)
            "plan": already["plan"],
            "card": None,
            "gate_counts": {},
            "withdrawn": withdrawn,
            "forgotten": forgotten,
            "sent_at": already["sent_at"],
            "memory": memory_state(),
        }
    session_manager = make_session(trip)
    run = build_decision_run(
        model_factory(trip, decision),
        kb,
        policy,
        trip,
        inbox=inbox,
        memory=memory,
        session_manager=session_manager,
        retry_strategy=retry_strategy,
    )
    answer = payload.get("answer")
    if answer is not None:
        card = inbox.get(trip.case_key)
        if card is not None and card.withdrawn_at is not None:  # a late answer to a closed question: nothing sent
            return {
                "state": "withdrawn",
                "plan": None,
                "card": card.to_dict(),
                "gate_counts": {},
                "withdrawn": withdrawn + [card.case_key],
                "forgotten": forgotten,
                "memory": memory_state(),
            }
        out = run.resume(bool(answer))
    else:
        out = run.start()
    counts = {
        "hook_cancel": run.bundle.hook.cancels,
        "guide_before_tool": run.bundle.gate.count(tracing.GUIDE_BEFORE),
        "guide_after_model": run.bundle.gate.count(tracing.GUIDE_AFTER),
        "interrupts": run.handler.count(tracing.INTERRUPT_RAISED),
    }
    if out.state in ("sent", "held") and out.plan is not None:
        sent.record(trip.case_key, out.plan.model_dump(), out.state)
    if run.superseded:  # the morning after: the night's open question closed, the plan sent without asking
        withdrawn = withdrawn + [run.superseded]
    return {
        "state": out.state,
        "composed_by": out.composed_by,  # model, or code (the cap, or an error)
        "plan": out.plan.model_dump() if out.plan else None,
        "card": out.card.to_dict() if out.card else None,
        "gate_counts": counts,
        "withdrawn": withdrawn,
        "forgotten": forgotten,  # decisions dropped because their outage ended (the next one asks afresh)
        "note": note_out,  # what the rider's note ruled out, and who read it (the model, or nothing)
        "memory": memory_state(),  # the durable copy: ok, degraded (with the reason and the backlog), or none
    }


def reset_session(make_session: Callable[[Trip], Any], trip: Trip) -> bool:
    """Delete the trip's session (Strands' session managers create one on construction, so a session that
    did not exist is created and deleted in one go). Returns whether a conversation was there to close."""
    manager = make_session(trip)
    if manager is None:
        return False
    existed = not getattr(manager, "_is_new_session", False)
    delete = getattr(manager, "delete_session", None)
    if delete is not None:
        delete(manager.session_id)
    return existed


def default_session_manager(data_dir: Path) -> Callable[[Trip], Any]:
    """One Strands session per rider and trip under data_dir, so a pause
    survives invocations on one container. The laptop swaps in
    S3SessionManager (same call shape) for the deployed runtime."""

    def make(trip: Trip):
        from strands.session.file_session_manager import FileSessionManager

        session_id = f"le-{trip.rider_id}-{trip.origin}-{trip.destination}"
        return FileSessionManager(session_id=session_id, storage_dir=str(data_dir / "sessions"))

    return make


def setup_observability() -> str:
    """AgentCore Observability: when the runtime provides an OTLP endpoint (the toolkit's ADOT setup sets
    OTEL_EXPORTER_OTLP_ENDPOINT), Strands' spans, including the gate events this package adds
    (hook.cancel_tool, steering.guide, steering.guide_after_model, steering.proceed_after_model,
    interrupt.raised, interrupt.resumed, delivery.*), go to CloudWatch through the OTLP exporter.
    Offline nothing is set up. Returns what was configured."""
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return "none (OTEL_EXPORTER_OTLP_ENDPOINT unset)"
    try:
        from strands.telemetry import StrandsTelemetry

        StrandsTelemetry().setup_otlp_exporter()
    except ImportError:  # the exporter package is the strands-agents[otel] extra; the runtime still serves
        return "unavailable (install strands-agents[otel])"
    return f"otlp ({os.environ['OTEL_EXPORTER_OTLP_ENDPOINT']})"


def make_runtime(model_factory: Callable[[Trip, Any], Any], **kwargs: Any):
    """Build the AgentCore app. Imports the SDK here so the module stays
    importable and testable without it."""
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    setup_observability()
    app = BedrockAgentCoreApp()

    kwargs.setdefault("decision_store_factory", decision_store_factory())  # from LAST_ELEVATOR_MEMORY_ID, or None
    kwargs.setdefault("retry_strategy", live.retry_strategy())  # one retry layer, bounded (le_dispatch/live.py)

    @app.entrypoint
    def invoke(payload: dict[str, Any], context: Any = None) -> dict[str, Any]:
        return handle(payload, model_factory=model_factory, **kwargs)

    return app


def bedrock_model_factory(model_id: str, region: str):
    """The live model on the live client configuration: botocore's own retries off, a read timeout, so the
    Strands layer the trace shows and the budget counts is the only one (le_dispatch/live.py)."""

    def make(trip: Trip, decision: Any):
        return live.model(model_id, region)

    return make


if __name__ == "__main__":  # laptop: python infra/agentcore/runtime/entrypoint.py, or `agentcore launch`
    model_id = os.environ.get("LAST_ELEVATOR_MODEL_ID", "us.amazon.nova-lite-v1:0")
    region = os.environ.get("AWS_REGION", "us-west-2")
    make_runtime(bedrock_model_factory(model_id, region)).run()
