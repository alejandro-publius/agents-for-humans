"""AgentCore Memory as the durable store for the rider's decisions.

A decision (the rider said yes or no to a reroute for one outage) lives in `agent.state`, which a Strands
session manager persists, and in a JSON mirror the app reads. On AgentCore Runtime a session is a microVM
that is reclaimed when idle, so a decision that must outlive it needs a store outside the runtime. Amazon
Bedrock AgentCore Memory is that store: one event per decision (`create_event`, a JSON payload and the case
key as indexed metadata), read back by case key (`list_events` with a metadata filter), under one actor id
per rider, expiring with the retention rule (`eventExpiryDuration`, the same number of days as
`make retention DAYS=`). The sent log (one outage, one message) keeps its durable copy the same way, as
"sent" events and a "cleared" event when the outage ends, and the inbox keeps its cards as "card" events,
so a fresh session sees an open question instead of asking it again.

The durable copy is best effort; the delivery is not. The stores call the service through
`ResilientMemoryClient`: a call that fails (a throttle, an outage, a permission error) marks the client
degraded with the reason and the store carries on with the session's own copy, so no invocation fails
because Memory did; a write that failed is kept and replayed before the next call, so the durable copy
catches up when the service does; and every write carries a client token derived from its content, so a
replay, or botocore's own retry, never duplicates an event. What an outage costs is stated: while Memory is
down, "never asked twice" and "one outage, one message" hold within the session, not across sessions.

Offline: `FakeMemoryClient` keeps the events in memory and validates every call against the service model
botocore ships as it is made, so the store's calls are known to be well formed before the first apply.
`make agentcore-memory` prints the resource plan (dry run); `--apply --yes` on the laptop creates the
Memory and prints its id for `LAST_ELEVATOR_MEMORY_ID`. Nothing here is called from the dispatch session.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from . import tracing
from .api_shapes import service_models_available, validate_call
from .interfaces import credentials_present as _credentials_present

DEFAULT_REGION = "us-west-2"
MEMORY_NAME = "last_elevator_decisions"
DECISIONS_SESSION = "decisions"  # one AgentCore Memory session per rider holds every decision
CASE_KEY = "case_key"
KIND = "kind"

IAM_PERMISSIONS = [
    "bedrock-agentcore:CreateMemory, GetMemory (the operator, once)",
    "bedrock-agentcore:CreateEvent, ListEvents, GetEvent on the memory (the runtime role and the poller)",
]


def credentials_present() -> bool:
    return _credentials_present()


def memory_plan(*, name: str = MEMORY_NAME, retention_days: int = 30, region: str = DEFAULT_REGION) -> dict[str, Any]:
    """The one control-plane call and its parameters: a Memory with the case key indexed for the filter and
    the retention rule as the event expiry."""
    return {
        "region": region,
        "calls": [
            (
                "bedrock-agentcore-control",
                "create_memory",
                {
                    "name": name,
                    "description": "Last Elevator: the rider's decisions per outage, expiring with the retention rule",
                    "eventExpiryDuration": retention_days,
                    "indexedKeys": [{"key": CASE_KEY, "type": "STRING"}, {"key": KIND, "type": "STRING"}],
                },
            )
        ],
        "iam": list(IAM_PERMISSIONS),
        "environment": "LAST_ELEVATOR_MEMORY_ID (the id create_memory returns) on the runtime and the poller",
    }


def render_plan(plan: dict[str, Any]) -> str:
    lines = [f"AgentCore Memory plan (region {plan['region']}); nothing below has been executed", ""]
    for i, (service, operation, params) in enumerate(plan["calls"], 1):
        lines.append(f"{i}. {service}.{operation}")
        for k, v in params.items():
            lines.append(f"     {k}: {json.dumps(v) if not isinstance(v, str) else v}")
    lines += [
        "     returns: memory.id, memory.arn (status CREATING, then ACTIVE)",
        "",
        "then, per decision, per delivery and per card, from the runtime and the poller (data plane):",
        "  create_event(memoryId, actorId=<rider id>, sessionId='decisions', eventTimestamp, "
        "payload=[{json: {content: {case_key, answer | entry | card | cleared}}}], metadata={case_key, kind})",
        "  list_events(memoryId, sessionId='decisions', actorId=<rider id>, includePayloads=true, "
        "filter={eventMetadata: [kind EQUALS_TO decision|sent|card, case_key EQUALS_TO <case key>]})",
        "",
        f"environment: {plan['environment']}",
        "",
        "IAM permissions needed:",
    ]
    lines.extend(f"  - {p}" for p in plan["iam"])
    return "\n".join(lines)


def create_event_params(
    memory_id: str, actor_id: str, case_key: str, content: dict[str, Any], when: dt.datetime, kind: str = "decision"
) -> dict:
    """One event: the case key and the content as a JSON payload, the case key and the kind as indexed metadata,
    and a client token derived from all of it (the API's idempotency token: the same write sent twice, by a
    replay or a retry, is stored once)."""
    token = hashlib.sha256(
        json.dumps(
            [memory_id, actor_id, case_key, kind, content, when.isoformat()], sort_keys=True, default=str
        ).encode()
    ).hexdigest()
    return {
        "memoryId": memory_id,
        "actorId": actor_id,
        "sessionId": DECISIONS_SESSION,
        "eventTimestamp": when,
        "payload": [{"json": {"content": {CASE_KEY: case_key, **content}}}],
        "metadata": {CASE_KEY: {"stringValue": case_key}, KIND: {"stringValue": kind}},
        "clientToken": token,
    }


def list_events_params(
    memory_id: str, actor_id: str, case_key: str | None = None, max_results: int = 100, kind: str = "decision"
) -> dict:
    params: dict[str, Any] = {
        "memoryId": memory_id,
        "sessionId": DECISIONS_SESSION,
        "actorId": actor_id,
        "includePayloads": True,
        "maxResults": max_results,
    }
    conditions = [
        {
            "left": {"metadataKey": KIND},
            "operator": "EQUALS_TO",
            "right": {"metadataValue": {"stringValue": kind}},
        }
    ]
    if case_key is not None:
        conditions.append(
            {
                "left": {"metadataKey": CASE_KEY},
                "operator": "EQUALS_TO",
                "right": {"metadataValue": {"stringValue": case_key}},
            }
        )
    params["filter"] = {"eventMetadata": conditions}
    return params


def _content_from_event(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for block in event.get("payload", []) or []:
        content = (block.get("json") or {}).get("content") if isinstance(block, dict) else None
        if isinstance(content, dict) and CASE_KEY in content:
            return str(content[CASE_KEY]), {k: v for k, v in content.items() if k != CASE_KEY}
    return None


def _stamp(event: dict[str, Any]) -> Any:
    return event.get("eventTimestamp") or dt.datetime.min.replace(tzinfo=dt.UTC)


MEMORY_ERRORS = (ClientError, BotoCoreError)  # what the service or the connection can raise; not a bug in the code


class ResilientMemoryClient:
    """The bedrock-agentcore client the stores call, made best effort. A call that fails with a service or
    connection error marks the client degraded (the reason is kept and put on the trace as `memory.degraded`)
    and returns nothing, so the store falls back to the session's own copy and the invocation goes on. A
    write that failed is kept in a backlog and replayed before the next call, in order; the replay carries
    the original client token, so the durable copy catches up without duplicates (`memory.replayed`). One
    instance per container, shared by every store, so the backlog outlives the invocation that filled it."""

    def __init__(self, client: Any):
        self.client = client
        self.backlog: list[dict[str, Any]] = []
        self.degraded: str | None = None  # the last failure's reason, None while the service answers
        self.failures = 0
        self.replayed = 0

    @property
    def status(self) -> dict[str, Any]:
        return {
            "status": "degraded" if self.degraded else "ok",
            "reason": self.degraded,
            "backlog": len(self.backlog),
            "replayed": self.replayed,
            "failures": self.failures,
        }

    def _fail(self, operation: str, exc: BaseException) -> None:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code") if isinstance(exc, ClientError) else None
        self.degraded = f"{operation}: {code or type(exc).__name__}"
        self.failures += 1
        tracing.record_event(tracing.MEMORY_DEGRADED, operation=operation, reason=self.degraded)

    def _flush(self) -> bool:
        """Replay the backlog in order; stop at the first failure (the rest waits for the next call)."""
        while self.backlog:
            params = self.backlog[0]
            try:
                self.client.create_event(**params)
            except MEMORY_ERRORS as exc:
                self._fail("create_event", exc)
                return False
            self.backlog.pop(0)
            self.replayed += 1
            tracing.record_event(tracing.MEMORY_REPLAYED, pending=len(self.backlog))
        return True

    def create_event(self, **params: Any) -> dict[str, Any]:
        if not self._flush():
            self.backlog.append(params)  # the service is still down: this write waits behind the others
            return {"event": {}}
        try:
            out = self.client.create_event(**params)
        except MEMORY_ERRORS as exc:
            self._fail("create_event", exc)
            self.backlog.append(params)
            return {"event": {}}
        self.degraded = None
        return out

    def list_events(self, **params: Any) -> dict[str, Any]:
        if not self._flush():
            return {"events": []}  # unknown, not empty: the caller keeps its own copy
        try:
            out = self.client.list_events(**params)
        except MEMORY_ERRORS as exc:
            self._fail("list_events", exc)
            return {"events": []}
        self.degraded = None
        return out


def memory_status(*stores: Any) -> dict[str, Any]:
    """The status of the resilient client behind these stores (the first one found), or "none"."""
    for store in stores:
        client = getattr(store, "client", None)
        if isinstance(client, ResilientMemoryClient):
            return client.status
    return {"status": "none" if not any(s is not None for s in stores) else "ok", "reason": None, "backlog": 0}


class AgentCoreEventStore:
    """Per-case records for one rider in AgentCore Memory: one event per write, the newest wins. `kind`
    separates what is stored ("decision": the answer; "sent": what was delivered)."""

    def __init__(self, client: Any, memory_id: str, actor_id: str, *, kind: str = "decision", clock: Any = None):
        self.client = client
        self.memory_id = memory_id
        self.actor_id = actor_id
        self.kind = kind
        self.clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self.calls = 0

    def put(self, case_key: str, content: dict[str, Any]) -> str:
        self.calls += 1
        params = create_event_params(self.memory_id, self.actor_id, case_key, content, self.clock(), self.kind)
        out = self.client.create_event(**params)
        return str((out.get("event") or {}).get("eventId", ""))

    def latest(self, case_key: str) -> dict[str, Any] | None:
        self.calls += 1
        events = self._events(case_key)  # the newest wins; on equal timestamps the later one listed
        newest = max(enumerate(events), key=lambda ie: (_stamp(ie[1]), ie[0]), default=None)
        found = _content_from_event(newest[1]) if newest else None
        return found[1] if found else None

    def all(self) -> dict[str, dict[str, Any]]:
        self.calls += 1
        out: dict[str, dict[str, Any]] = {}
        for _, event in sorted(enumerate(self._events(None)), key=lambda ie: (_stamp(ie[1]), ie[0])):
            found = _content_from_event(event)
            if found:
                out[found[0]] = found[1]
        return out

    def _events(self, case_key: str | None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        token = None
        while True:
            params = list_events_params(self.memory_id, self.actor_id, case_key, kind=self.kind)
            if token:
                params["nextToken"] = token
            page = self.client.list_events(**params)
            events.extend(page.get("events", []) or [])
            token = page.get("nextToken")
            if not token:
                return events


class AgentCoreDecisionStore(AgentCoreEventStore):
    """The rider's decisions: get(case_key) -> bool | None, set(case_key, answer)."""

    def __init__(self, client: Any, memory_id: str, actor_id: str, *, clock: Any = None):
        super().__init__(client, memory_id, actor_id, kind="decision", clock=clock)

    def set(self, case_key: str, answer: bool) -> str:
        return self.put(case_key, {"answer": bool(answer)})

    def get(self, case_key: str) -> bool | None:
        found = self.latest(case_key)
        return bool(found["answer"]) if found and "answer" in found else None

    def items(self) -> dict[str, bool]:
        return {k: bool(v["answer"]) for k, v in self.all().items() if "answer" in v}

    def clear(self, case_key: str) -> str:
        """The outage ended: a cleared event, so the next outage of the same elevator is a new decision."""
        return self.put(case_key, {"cleared": True})


class AgentCoreCardStore(AgentCoreEventStore):
    """The rider's decision cards (the inbox's durable copy): the card's whole state on every change, so a
    fresh runtime session sees an open question instead of asking it again."""

    def __init__(self, client: Any, memory_id: str, actor_id: str, *, clock: Any = None):
        super().__init__(client, memory_id, actor_id, kind="card", clock=clock)

    def put_card(self, card: dict[str, Any]) -> str:
        return self.put(str(card["case_key"]), {"card": card})

    def get_card(self, case_key: str) -> dict[str, Any] | None:
        found = self.latest(case_key)
        return found.get("card") if found else None

    def open_cards(self) -> list[dict[str, Any]]:
        return [
            v["card"]
            for v in self.all().values()
            if v.get("card") and v["card"].get("answer") is None and not v["card"].get("withdrawn_at")
        ]


class AgentCoreSentStore(AgentCoreEventStore):
    """What was delivered per case (the sent log's durable copy): a "sent" event per delivery, a "cleared"
    event when the outage ended, so a fresh runtime session does not send the same plan again."""

    def __init__(self, client: Any, memory_id: str, actor_id: str, *, clock: Any = None):
        super().__init__(client, memory_id, actor_id, kind="sent", clock=clock)

    def record(self, case_key: str, entry: dict[str, Any]) -> str:
        return self.put(case_key, {"entry": entry})

    def get(self, case_key: str) -> dict[str, Any] | None:
        found = self.latest(case_key)
        return found.get("entry") if found and not found.get("cleared") else None

    def clear(self, case_key: str) -> str:
        return self.put(case_key, {"cleared": True})

    def keys(self) -> list[str]:
        return [k for k, v in self.all().items() if not v.get("cleared")]


@dataclass
class FakeMemoryClient:
    """An in-memory bedrock-agentcore client for the tests: every call's shape is validated against the
    service model as it is made (when botocore ships it), then applied to a dict of events."""

    events: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    page_size: int = 1000

    def _check(self, operation: str, params: dict[str, Any]) -> None:
        self.calls.append((operation, params))
        if service_models_available():
            problem = validate_call("bedrock-agentcore", operation, params)
            if problem:
                raise ValueError(f"{operation}: {problem}")

    def create_event(self, **params: Any) -> dict[str, Any]:
        self._check("create_event", params)
        token = params.get("clientToken")
        for seen in self.events:  # the API's idempotency token: a repeated token is ignored, no error
            if token and seen.get("clientToken") == token:
                return {"event": seen}
        event = {
            "clientToken": token,
            "eventId": f"evt-{len(self.events) + 1:06d}",
            "memoryId": params["memoryId"],
            "actorId": params["actorId"],
            "sessionId": params.get("sessionId"),
            "eventTimestamp": params["eventTimestamp"],
            "payload": params["payload"],
            "metadata": params.get("metadata", {}),
        }
        self.events.append(event)
        return {"event": event}

    def list_events(self, **params: Any) -> dict[str, Any]:
        self._check("list_events", params)
        conditions = (params.get("filter") or {}).get("eventMetadata", [])
        matching = []
        for e in self.events:
            if e["memoryId"] != params["memoryId"] or e["actorId"] != params["actorId"]:
                continue
            if e.get("sessionId") != params["sessionId"]:
                continue
            ok = True
            for c in conditions:
                key = c["left"]["metadataKey"]
                want = c["right"]["metadataValue"]["stringValue"]
                have = (e.get("metadata", {}).get(key) or {}).get("stringValue")
                if c["operator"] == "EQUALS_TO" and have != want:
                    ok = False
            if ok:
                hidden = ("clientToken",) if params.get("includePayloads") else ("clientToken", "payload")
                matching.append({k: v for k, v in e.items() if k not in hidden})
        start = int(params.get("nextToken") or 0)
        page = matching[start : start + self.page_size]
        out: dict[str, Any] = {"events": page}
        if start + self.page_size < len(matching):
            out["nextToken"] = str(start + self.page_size)
        return out


def apply(plan: dict[str, Any], *, yes: bool = False, region: str = DEFAULT_REGION) -> dict[str, Any]:
    """Laptop only: create the Memory; refuses without credentials and --yes."""
    if not credentials_present():
        raise RuntimeError("no AWS credentials in the environment; use --dry-run")
    if not yes:
        raise RuntimeError("refusing to create resources without --yes")
    import boto3  # imported here so the package never needs boto3 for dry runs

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    _service, _operation, params = plan["calls"][0]
    memory = client.create_memory(**params)["memory"]
    return {"memoryId": memory["id"], "memoryArn": memory.get("arn"), "status": memory.get("status")}
