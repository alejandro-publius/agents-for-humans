"""F2: the human moment. After dark and at last train, the run pauses.

Mechanics (strands-agents 1.55.1, confirmed by running it offline):
- `steer_before_tool` returns `Interrupt(reason=...)`. The SDK calls
  `event.interrupt(name="steering_input_<tool>", reason={"message": ...})`,
  the agent stops with `stop_reason == "interrupt"` and `result.interrupts`.
- The caller resumes with
  `agent([{"interruptResponse": {"interruptId": id, "response": True|False}}])`.
  The hook runs again, the handler returns `Interrupt` again, and this time
  `event.interrupt` returns the stored response: True lets the tool run,
  False cancels it with "Manual approval denied".
- Interrupts are session managed between the return and the response, so a
  session manager persists the pause across processes.

What this module adds on top:
- A DecisionCard (BART's option, added minutes from the policy engine, the
  flags, the source URL, the rejected options with one-line reasons) written
  to the rider's inbox in the app when the run pauses.
- DecisionMemory: the rider's answer stored in session state (agent.state,
  which Strands session managers persist) and mirrored to JSON for the app,
  so the same case does not interrupt again.
- DecisionRun: start / resume with a scripted or real human answer.
- Decline semantics: the tool is cancelled by the SDK and the final Plan must
  carry status "hold"; a Plan with status "send" after a decline is Guided.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strands import Agent
from strands.types.interrupt import InterruptResponseContent
from strands.vended_plugins.steering.core.action import Guide, Interrupt, Proceed
from strands.vended_plugins.steering.core.handler import SteeringHandler

from . import tracing
from .budget import expected_cap
from .gates import AgentBundle, GateEvent, build_agent, extract_plan, trip_prompt
from .interfaces import KBSet, PolicyCallable, PolicyDecision, Trip
from .messages import KIND_WORDS, LABEL_WORDS_PLAIN, composed_plan
from .plan import PLAN_TOOL_NAME, Plan

try:  # POSIX (the laptop, the runtime container): an advisory lock serializes the poller and the app
    import fcntl
except ImportError:  # pragma: no cover - Windows: single-process use only, the atomic rename still holds
    fcntl = None  # type: ignore[assignment]

DECISION_STATE_KEY = "last_elevator.decisions"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class DecisionCard:
    """What the rider sees when the agent needs a real decision."""

    case_key: str
    rider_id: str
    station: str
    elevator: str
    option: str
    added_minutes: int | None
    flags: dict[str, bool]
    source_url: str
    rejected: list[dict[str, str]]
    question: str
    created_at: str = field(default_factory=_now)
    answer: bool | None = None
    answered_at: str | None = None
    interrupt_ids: list[str] = field(default_factory=list)  # Strands interrupt ids, for a resume from another process
    withdrawn_at: str | None = None  # set when the outage ended before the rider answered: no decision needed
    withdrawn_reason: str = ""

    @property
    def open(self) -> bool:
        """Still waiting for the rider: unanswered and not withdrawn."""
        return self.answer is None and self.withdrawn_at is None

    @classmethod
    def from_decision(cls, trip: Trip, d: PolicyDecision) -> DecisionCard:
        question = card_question(d)
        return cls(
            case_key=trip.case_key,
            rider_id=trip.rider_id,
            station=d.station or "",
            elevator=d.elevator or "",
            option=d.top_option or "",
            added_minutes=d.minutes_for(d.top_option),
            flags=dict(d.flags),
            source_url=d.source_url,
            rejected=[{"label": o.label, "reason": o.reason} for o in d.rejected()],
            question=question,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """An advisory lock (a `.lock` file next to `path`) around a read-modify-write, so the poller and the
    app never lose each other's change. A no-op where fcntl is absent (single-process use)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "a+") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def atomic_write_json(path: Path, document: Any) -> None:
    """Write a temporary file and rename it into place: a reader sees the old file or the new one, never a
    torn one (atomic on POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(document, indent=2) + "\n")
    os.replace(tmp, path)


WHY = {"after_dark": "It is after dark.", "last_train": "This is the last train."}
WITHDRAWN_REASON = "the elevator is back in service; no decision needed"
SUPERSEDED_REASON = "no longer after dark or the last train; the plan is sent without asking"


def card_question(d: PolicyDecision) -> str:
    """The question a rider hears, in plain words: the station's name when the KB has one, BART's option
    in words rather than a label, the policy engine's minutes."""
    why = " ".join(WHY[k] for k in ("after_dark", "last_train") if d.flags.get(k)) or "This needs your decision."
    words = LABEL_WORDS_PLAIN.get(d.top_option or "", d.top_option or "")
    minutes = d.minutes_for(d.top_option)
    tail = f", about {minutes} minutes more" if minutes else ""
    where = KIND_WORDS.get(d.kind or "", "")
    out = f"is out {where}" if where else "is out"
    note = ""
    if d.note_constraints:
        from .note import plain_words

        said = plain_words(d.note_constraints)
        note = (
            f" You asked for {said} today, and no option is left, so this is BART's order."
            if d.note_set_aside
            else f" You asked for {said} today."
        )
    return (
        f"{why} {d.spoken_station} elevator {d.elevator} {out}. BART's option is {words}{tail}.{note} "
        "Send this plan now?"
    )


class Inbox:
    """Rider inbox as a JSON file: {"cards": [DecisionCard...]}. The app lists
    cards whose answer is null and posts the answer back with `answer()`.

    The poller writes cards while the app answers them, so every
    read-modify-write holds a lock file next to the inbox and every save is
    atomic (a temporary file renamed into place): a reader never sees a
    half-written inbox and two writers never lose each other's change."""

    def __init__(self, path: str | Path, store: Any = None):
        self.path = Path(path)
        self.store = store  # the durable copy of this rider's cards (AgentCore Memory): put_card, get_card, open_cards

    def _locked(self) -> contextlib.AbstractContextManager[None]:
        return file_lock(self.path)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text()).get("cards", [])

    def _save(self, cards: list[dict[str, Any]]) -> None:
        atomic_write_json(self.path, {"cards": cards})

    def _mirror(self, case_key: str, cards: list[dict[str, Any]]) -> None:
        """Write the card's current state through to the durable copy."""
        if self.store is not None:
            for c in cards:
                if c["case_key"] == case_key:
                    self.store.put_card(c)

    def write(self, card: DecisionCard) -> None:
        with self._locked():
            cards = [c for c in self._load() if c["case_key"] != card.case_key]
            cards.append(card.to_dict())
            self._save(cards)
        self._mirror(card.case_key, cards)

    def get(self, case_key: str) -> DecisionCard | None:
        for c in self._load():
            if c["case_key"] == case_key:
                return DecisionCard(**c)
        if self.store is not None:  # a card another session wrote: the durable copy, cached here
            c = self.store.get_card(case_key)
            if c is not None:
                with self._locked():
                    cards = [x for x in self._load() if x["case_key"] != case_key] + [c]
                    self._save(cards)
                return DecisionCard(**c)
        return None

    def pending(self, rider_id: str | None = None) -> list[DecisionCard]:
        return [
            card
            for card in (DecisionCard(**c) for c in self._load())
            if card.open and (rider_id is None or card.rider_id == rider_id)
        ]

    def purge(self, *, older_than_days: int, now: datetime | None = None) -> list[str]:
        """Retention: drop closed cards (answered or withdrawn) older than the given number of days. Open
        cards are never purged, whatever their age. Returns the purged case keys."""
        cutoff = (now or datetime.now(UTC)).timestamp() - older_than_days * 86400
        purged: list[str] = []
        with self._locked():
            cards = self._load()
            keep = []
            for c in cards:
                card = DecisionCard(**c)
                closed_at = card.answered_at or card.withdrawn_at
                if not card.open and closed_at and datetime.fromisoformat(closed_at).timestamp() < cutoff:
                    purged.append(card.case_key)
                else:
                    keep.append(c)
            if purged:
                self._save(keep)
        return purged

    def withdraw_stale(self, trip: Trip, reason: str = WITHDRAWN_REASON) -> list[str]:
        """Withdraw this rider and trip's open cards whose elevator is no longer out. The question must not
        outlive the outage: a card the rider never answered is closed, never re-asked, and a late answer to
        it is refused. Returns the withdrawn case keys."""
        prefix = f"{trip.rider_id}|{trip.origin}>{trip.destination}|"
        withdrawn: list[str] = []
        with self._locked():
            cards = self._load()
            if self.store is not None:  # open cards another session wrote for this rider
                known = {c["case_key"] for c in cards}
                cards += [c for c in self.store.open_cards() if c["case_key"] not in known]
            for c in cards:
                card = DecisionCard(**c)
                if not card.open or not card.case_key.startswith(prefix):
                    continue
                if card.elevator and card.elevator not in trip.outages:
                    c["withdrawn_at"] = _now()
                    c["withdrawn_reason"] = reason
                    withdrawn.append(card.case_key)
            if withdrawn:
                self._save(cards)
        for key in withdrawn:
            self._mirror(key, cards)
        return withdrawn

    def withdraw(self, case_key: str, reason: str) -> bool:
        """Close one open card with a reason (the question is moot: the daytime rule sends without asking).
        Returns whether a card was closed."""
        closed = False
        with self._locked():
            cards = self._load()
            for c in cards:
                if c["case_key"] == case_key and DecisionCard(**c).open:
                    c["withdrawn_at"] = _now()
                    c["withdrawn_reason"] = reason
                    closed = True
            if closed:
                self._save(cards)
        if closed:
            self._mirror(case_key, cards)
        return closed

    def answer(self, case_key: str, answer: bool) -> None:
        with self._locked():
            cards = self._load()
            for c in cards:
                if c["case_key"] == case_key:
                    c["answer"] = answer
                    c["answered_at"] = _now()
            self._save(cards)
        self._mirror(case_key, cards)

    def set_interrupts(self, case_key: str, interrupt_ids: list[str]) -> None:
        with self._locked():
            cards = self._load()
            for c in cards:
                if c["case_key"] == case_key:
                    c["interrupt_ids"] = list(interrupt_ids)
            self._save(cards)
        self._mirror(case_key, cards)


class SentLog:
    """One outage, one message. What was delivered per case, as a JSON file the poller consults before it
    runs anything: a plan already sent for this case (this rider, this trip, this elevator) is not sent
    again on the next poll, and no model is called for it. When the elevator comes back, the entries for
    that trip are cleared, so a later outage of the same elevator is a new message. Same locking and
    atomic saves as the inbox."""

    def __init__(self, path: str | Path, store: Any = None):
        self.path = Path(path)
        self.store = store  # the durable copy (AgentCore Memory): get, record, clear, keys

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def _save(self, entries: dict[str, Any]) -> None:
        atomic_write_json(self.path, entries)

    def get(self, case_key: str) -> dict[str, Any] | None:
        entry = self._load().get(case_key)
        if entry is None and self.store is not None:  # delivered by another session: the durable copy
            entry = self.store.get(case_key)
            if entry is not None:
                with file_lock(self.path):
                    entries = self._load()
                    entries[case_key] = entry
                    self._save(entries)
        return entry

    def record(self, case_key: str, plan: dict[str, Any], state: str) -> None:
        entry = {"state": state, "plan": plan, "sent_at": _now()}
        with file_lock(self.path):
            entries = self._load()
            entries[case_key] = entry
            self._save(entries)
        if self.store is not None:
            self.store.record(case_key, entry)

    def clear_stale(self, trip: Trip) -> list[str]:
        """The outage ended for this trip: forget its entries whose elevator is no longer out."""
        prefix = f"{trip.rider_id}|{trip.origin}>{trip.destination}|"
        cleared: list[str] = []
        with file_lock(self.path):
            entries = self._load()
            for key in list(entries):
                if key.startswith(prefix) and key[len(prefix) :] not in trip.outages:
                    del entries[key]
                    cleared.append(key)
            if cleared:
                self._save(entries)
        if self.store is not None:
            for key in self.store.keys():
                if key.startswith(prefix) and key[len(prefix) :] not in trip.outages:
                    self.store.clear(key)
                    if key not in cleared:
                        cleared.append(key)
        return cleared


class DecisionMemory:
    """Answers by case_key. Lives in agent.state (persisted by Strands session
    managers) and in an optional JSON mirror the app can read without an agent.
    With a durable store (AgentCore Memory, `le_dispatch/agentcore_memory.py`)
    every answer is written through to it and a case unknown here is read
    from it, so a decision outlives the runtime session that took it.

    A decision belongs to its outage: when the elevator is back, the answer
    is forgotten (`clear_stale`, called on every poll) in the mirror, the
    session's copy and the durable copy (a cleared event), so the next
    outage of the same elevator asks afresh instead of being held or sent
    on an old answer. The session's copy can outlive the clearing (it is
    restored by the session manager on the next run), so the mirror keeps a
    tombstone per cleared key and `attach` drops what the tombstones or the
    durable copy say is gone."""

    def __init__(self, path: str | Path | None = None, store: Any = None):
        self.path = Path(path) if path else None
        self.store = store  # get(case_key) -> bool | None, set(case_key, answer); the durable copy
        self._agent: Agent | None = None
        self._local: dict[str, bool] = self._read_mirror()
        self._tombstones: set[str] = self._read_tombstones()

    @property
    def tombstones_path(self) -> Path | None:
        return self.path.with_name(self.path.stem + "-cleared.json") if self.path else None

    def _read_mirror(self) -> dict[str, bool]:
        if self.path and self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def _read_tombstones(self) -> set[str]:
        path = self.tombstones_path
        if path and path.exists():
            return set(json.loads(path.read_text()))
        return set()

    def _write_tombstones(self) -> None:
        if self.tombstones_path:
            atomic_write_json(self.tombstones_path, sorted(self._tombstones))

    @staticmethod
    def _stale(trip: Trip, case_key: str) -> bool:
        prefix = f"{trip.rider_id}|{trip.origin}>{trip.destination}|"
        return case_key.startswith(prefix) and case_key[len(prefix) :] not in trip.outages

    def clear_stale(self, trip: Trip) -> list[str]:
        """The outage ended for this trip: forget its decisions whose elevator is no longer out. Returns the
        case keys (from the mirror, the session's copy when attached, and the durable copy)."""
        cleared = [k for k in self._local if self._stale(trip, k)]
        if self._agent is not None:
            stored = self._agent.state.get(DECISION_STATE_KEY) or {}
            cleared += [k for k in stored if self._stale(trip, k) and k not in cleared]
        if self.store is not None and hasattr(self.store, "items"):
            cleared += [k for k in self.store.items() if self._stale(trip, k) and k not in cleared]
        for key in cleared:
            self._local.pop(key, None)
            self._tombstones.add(key)
            if self.store is not None and hasattr(self.store, "clear"):
                self.store.clear(key)
            tracing.record_event(tracing.DECISION_CLEARED, case_key=key)
        if cleared:
            if self._agent is not None:
                stored = {
                    k: v for k, v in (self._agent.state.get(DECISION_STATE_KEY) or {}).items() if k not in cleared
                }
                self._agent.state.set(DECISION_STATE_KEY, stored)
            if self.path:
                atomic_write_json(self.path, self._local)
            self._write_tombstones()
        return cleared

    def attach(self, agent: Agent) -> None:
        self._agent = agent
        stored = agent.state.get(DECISION_STATE_KEY) or {}
        merged = dict(self._local)
        for key, answer in stored.items():  # the session's copy: dropped where the outage is known to have ended
            if key in merged or key in self._tombstones:
                continue
            if self.store is not None and self.store.get(key) is None:
                continue  # the durable copy cleared it (or never had it)
            merged[key] = answer
        agent.state.set(DECISION_STATE_KEY, merged)
        self._local = merged

    def get(self, case_key: str) -> bool | None:
        if self._agent is not None:
            stored = self._agent.state.get(DECISION_STATE_KEY) or {}
            if case_key in stored:
                return stored[case_key]
        if case_key in self._local:
            return self._local[case_key]
        if self.store is not None:  # a decision taken in another session: the durable copy
            answer = self.store.get(case_key)
            if answer is not None:
                self._remember(case_key, answer)
            return answer
        return None

    def set(self, case_key: str, answer: bool) -> None:
        if case_key in self._tombstones:  # a new outage's decision: the old tombstone is spent
            self._tombstones.discard(case_key)
            self._write_tombstones()
        self._remember(case_key, answer)
        if self.store is not None:
            self.store.set(case_key, answer)

    def _remember(self, case_key: str, answer: bool) -> None:
        self._local[case_key] = answer
        if self._agent is not None:
            stored = dict(self._agent.state.get(DECISION_STATE_KEY) or {})
            stored[case_key] = answer
            self._agent.state.set(DECISION_STATE_KEY, stored)
        if self.path:
            atomic_write_json(self.path, self._local)


def needs_human(d: PolicyDecision) -> bool:
    return bool(d.affected and (d.flags.get("after_dark") or d.flags.get("last_train")))


class DecisionInterruptHandler(SteeringHandler):
    """Interrupt before draft_plan when the decision is the rider's to make."""

    name = "decision_interrupt"

    def __init__(
        self,
        *,
        policy: PolicyCallable,
        trip: Trip,
        inbox: Inbox,
        memory: DecisionMemory,
        plan_tool: str = PLAN_TOOL_NAME,
        plan_model: type[Plan] = Plan,
    ):
        super().__init__()
        self.policy = policy
        self.trip = trip
        self.inbox = inbox
        self.memory = memory
        self.plan_tool = plan_tool
        self.plan_model = plan_model
        self.events: list[GateEvent] = []
        self.pending_answer: bool | None = None  # set by DecisionRun.resume for the resumed pass
        self.pending_interrupt_ids: list[str] = []  # the interrupt(s) being answered on the resumed pass
        self._raised = False
        self._decision: PolicyDecision | None = None

    @property
    def decision(self) -> PolicyDecision:
        if self._decision is None:
            self._decision = self.policy(self.trip)
        return self._decision

    def count(self, kind: str) -> int:
        return sum(1 for e in self.events if e.kind == kind)

    def remembered(self) -> bool | None:
        if self.pending_answer is not None:
            return self.pending_answer
        return self.memory.get(self.trip.case_key)

    def is_interrupted_call(self, tool_use: Any) -> bool:
        """Is this the tool call the pending interrupt was raised on? Strands keys a before-tool interrupt by
        the tool use id (`v1:before_tool_call:<toolUseId>:...`); the card carries the ids."""
        tool_use_id = str(tool_use.get("toolUseId", ""))
        if not self.pending_interrupt_ids:
            return True  # no ids known (an older card): keep the SDK protocol for the first call
        return any(f":{tool_use_id}:" in i for i in self.pending_interrupt_ids)

    async def steer_before_tool(self, *, agent: Agent, tool_use: Any, **kwargs: Any):
        if tool_use["name"] != self.plan_tool:
            return Proceed(reason="not the plan tool")
        d = self.decision
        if not needs_human(d):
            return Proceed(reason="routine case: no human decision needed")
        # On the resumed pass the answer is already in memory (so the session persists it); the SDK still
        # needs the Interrupt returned once more, for the interrupted tool call only, to hand the answer
        # back. Any other draft_plan call in the same pass (a gate cancelled the resumed call and the model
        # retried) is decided on the answer: asking again would raise a second interrupt for a new tool use
        # id, and the rider would be asked twice.
        resumed_call = self.pending_answer is not None and self.is_interrupted_call(tool_use)
        stored = self.pending_answer if self.pending_answer is not None else self.memory.get(self.trip.case_key)
        if stored is True and not resumed_call:
            return Proceed(reason="rider already approved this case")
        if stored is False and not resumed_call:
            reason = (
                "The rider already declined this reroute for this outage. Do not draft it again; "
                "return the Plan with status 'hold' and a one-sentence message that the plan is on file."
            )
            self.events.append(GateEvent(tracing.GUIDE_BEFORE, tool_use["name"], reason))
            return Guide(reason=reason)
        card = DecisionCard.from_decision(self.trip, d)
        if not self._raised:
            self.inbox.write(card)
            self._raised = True
            self.events.append(GateEvent(tracing.INTERRUPT_RAISED, tool_use["name"], card.question, card.to_dict()))
            tracing.add_span_event(
                tracing.INTERRUPT_RAISED, case_key=card.case_key, option=card.option, flags=json.dumps(card.flags)
            )
        if self.pending_answer is not None:
            # the resumed pass: the SDK hands back the stored answer inside this same span
            tracing.add_span_event(tracing.INTERRUPT_RESUMED, case_key=card.case_key, answer=self.pending_answer)
        # Returned again on the resumed pass so the SDK can hand back the stored answer.
        return Interrupt(reason=card.question)

    async def steer_after_model(self, *, agent: Agent, message: Any, stop_reason: str, **kwargs: Any):
        plan = extract_plan(message, self.plan_model.__name__)
        if plan is None or not needs_human(self.decision):
            return Proceed(reason="no plan, or routine case")
        answer = self.remembered()
        status = plan.get("status", "send")
        if answer is False and status != "hold":
            reason = (
                "The rider declined this reroute. Return the Plan with status 'hold', "
                "keeping the policy engine's values."
            )
            self.events.append(GateEvent(tracing.GUIDE_AFTER, self.plan_model.__name__, reason, plan))
            tracing.add_span_event(tracing.GUIDE_AFTER, reason=reason)
            return Guide(reason=reason)
        if answer is not False and status == "hold":
            reason = "Only the rider can put a plan on hold. Return the Plan with status 'send'."
            self.events.append(GateEvent(tracing.GUIDE_AFTER, self.plan_model.__name__, reason, plan))
            tracing.add_span_event(tracing.GUIDE_AFTER, reason=reason)
            return Guide(reason=reason)
        return Proceed(reason="plan status matches the rider's decision")


@dataclass
class RunOutcome:
    state: str  # pending | sent | held
    plan: Plan | None = None
    card: DecisionCard | None = None
    interrupt_ids: list[str] = field(default_factory=list)
    composed_by: str = "model"  # "model" | "code" (fallback after the turn cap) | "none" (pending)


def is_paused(agent: Agent) -> bool:
    """Does this agent (its session restored) hold an interrupt waiting for a response? Strands keeps that
    in the agent's interrupt state, which the session manager persists; a fresh session after a recycled
    container holds none, and a prompt sent to a paused agent is refused by the SDK (it must be the
    interrupt responses), so the run checks before it invokes."""
    state = getattr(agent, "_interrupt_state", None)
    return bool(getattr(state, "activated", False))


class DecisionRun:
    """One agent run that may pause for the rider and resume with an answer.

    An answer never fails and a question never blocks: an open question whose rule no longer holds (it was
    after dark; the outage is still on in the morning) is closed as superseded and the plan is sent; an
    answer that arrives after the container was recycled (no paused run to resume) is remembered and the
    plan is drafted afresh under it; an answer to a case that was never asked is taken the same way."""

    def __init__(
        self,
        bundle: AgentBundle,
        handler: DecisionInterruptHandler,
        prompt: str | None = None,
        max_turns: int = 8,
    ):
        self.bundle = bundle
        self.handler = handler
        self.prompt = prompt if prompt is not None else trip_prompt(bundle.trip, bundle.decision)
        self.max_turns = max_turns
        self.outcome: RunOutcome | None = None
        self.superseded: str | None = None  # the case key of a question closed because its rule no longer held

    def _finish(self, result: Any) -> RunOutcome:
        card = self.handler.inbox.get(self.handler.trip.case_key)
        if result is not None and result.stop_reason == "interrupt":
            ids = [i.id for i in result.interrupts]
            self.handler.inbox.set_interrupts(self.handler.trip.case_key, ids)
            card = self.handler.inbox.get(self.handler.trip.case_key)
            self.outcome = RunOutcome("pending", card=card, interrupt_ids=ids, composed_by="none")
            return self.outcome
        plan = result.structured_output if result is not None else None
        composed_by = "model"
        gate = self.bundle.gate
        if isinstance(plan, Plan) and gate is not None:
            # the last line, as in deliver(): the same checks once more before anything reaches the rider
            problems = gate.check_plan(plan.model_dump())
            if problems:
                tracing.add_span_event("delivery.final_check_failed", reason="; ".join(problems))
                plan = None
        if not isinstance(plan, Plan):
            # the model never produced an approved plan within the turn cap: code composes it
            answer = self.handler.remembered()
            status = "hold" if answer is False else "send"
            plan = Plan(**composed_plan(self.handler.decision, status))
            composed_by = "code"
            tracing.add_span_event("delivery.composed_by_code", reason=str(getattr(result, "stop_reason", "exception")))
        state = "held" if plan.status == "hold" else "sent"
        self.outcome = RunOutcome(state, plan=plan, card=card, composed_by=composed_by)
        return self.outcome

    def _invoke(self, prompt: Any) -> Any:
        try:
            with expected_cap():
                return self.bundle.agent(prompt, limits={"turns": self.max_turns})
        except Exception as exc:  # the rider still gets a plan; the packet records why
            tracing.add_span_event("delivery.run_failed", reason=repr(exc))
            return None

    def start(self) -> RunOutcome:
        """Run, or, if this case already has an unanswered card in the inbox,
        report it as pending without asking the rider again (the poller runs
        every five minutes; the rider decides once)."""
        waiting = self.handler.inbox.get(self.handler.trip.case_key)
        if waiting is not None and waiting.open and waiting.interrupt_ids:
            if needs_human(self.handler.decision):
                self.outcome = RunOutcome(
                    "pending", card=waiting, interrupt_ids=list(waiting.interrupt_ids), composed_by="none"
                )
                self.handler._raised = True
                return self.outcome
            # the morning after: the outage is still on, the rider never answered, and the rule that asked
            # (after dark, the last train) no longer holds; the question is closed as superseded, the paused
            # run released (the handler proceeds on the daytime rule and never reads the response), and the
            # plan is sent the way any daytime plan is
            self.handler.inbox.withdraw(self.handler.trip.case_key, SUPERSEDED_REASON)
            self.superseded = self.handler.trip.case_key
            self.handler.events.append(GateEvent(tracing.INTERRUPT_SUPERSEDED, PLAN_TOOL_NAME, SUPERSEDED_REASON))
            tracing.record_event(tracing.INTERRUPT_SUPERSEDED, case_key=self.superseded, reason=SUPERSEDED_REASON)
            if is_paused(self.bundle.agent):
                return self._finish(self._invoke(self._responses(waiting.interrupt_ids, True)))
        return self._finish(self._invoke(self.prompt))

    @staticmethod
    def _responses(interrupt_ids: list[str], answer: bool) -> list[InterruptResponseContent]:
        return [{"interruptResponse": {"interruptId": i, "response": answer}} for i in interrupt_ids]

    def resume(self, answer: bool) -> RunOutcome:
        """Resume a paused run. Works in the same process (after start()) or
        in a new one: with a session manager, the inbox card carries the
        interrupt ids and the session carries the pending interrupt."""
        case_key = self.handler.trip.case_key
        if self.outcome is None:
            card = self.handler.inbox.get(case_key)
            if card is not None and card.withdrawn_at is not None:
                raise RuntimeError(f"card withdrawn: {card.withdrawn_reason}")
            ids = list(card.interrupt_ids) if card is not None and card.open else []
            self.outcome = RunOutcome("pending", card=card, interrupt_ids=ids, composed_by="none")
            self.handler._raised = card is not None  # the card exists; do not write it again on the resumed pass
        if self.outcome.state != "pending":
            raise RuntimeError("nothing to resume")
        if self.outcome.card is not None and self.outcome.card.open:
            self.handler.inbox.answer(case_key, answer)
        self.handler.events.append(GateEvent(tracing.INTERRUPT_RESUMED, PLAN_TOOL_NAME, str(answer)))
        # store before the resumed invocation so the session manager persists it with the run
        self.handler.memory.set(case_key, answer)
        if not (self.outcome.interrupt_ids and is_paused(self.bundle.agent)):
            # no paused run to hand the answer to (the container was recycled, or the question was never
            # asked here): the answer is remembered and the plan drafted afresh under it, so the model
            # composes it, the handler proceeding or holding on the remembered answer
            tracing.record_event(tracing.INTERRUPT_RESUMED, case_key=case_key, answer=answer, paused=False)
            return self._finish(self._invoke(self.prompt))
        self.handler.pending_answer = answer
        self.handler.pending_interrupt_ids = list(self.outcome.interrupt_ids)
        try:
            result = self._invoke(self._responses(self.outcome.interrupt_ids, answer))
        finally:
            self.handler.pending_answer = None
            self.handler.pending_interrupt_ids = []
        return self._finish(result)


def build_decision_run(
    model: Any,
    kb: KBSet,
    policy: PolicyCallable,
    trip: Trip,
    *,
    inbox: Inbox,
    memory: DecisionMemory,
    prompt: str | None = None,
    session_manager: Any = None,
    max_turns: int = 8,
    retry_strategy: Any = None,
) -> DecisionRun:
    """Full stack plus the decision handler; memory is attached to agent.state,
    which the session manager (if any) persists across processes."""
    handler = DecisionInterruptHandler(policy=policy, trip=trip, inbox=inbox, memory=memory)
    bundle = build_agent(
        model,
        kb,
        policy,
        trip,
        extra_plugins=(handler,),
        session_manager=session_manager,
        retry_strategy=retry_strategy,
    )
    memory.attach(bundle.agent)
    return DecisionRun(bundle, handler, prompt, max_turns=max_turns)


def demo_after_dark(kb: KBSet, policy: PolicyCallable, trip: Trip, exporter: Any = None) -> int:
    """make demo-one --after-dark: pause, card in the inbox, scripted rider says yes, resume."""
    import tempfile

    from .scripted_model import ScriptedModel, plan_call, tool_call

    d = policy(trip)
    plan = composed_plan(d)
    script = [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        plan_call(plan, "p1"),
    ]
    tmp = Path(tempfile.mkdtemp(prefix="le-demo-"))
    inbox, memory = Inbox(tmp / "inbox.json"), DecisionMemory(tmp / "decisions.json")

    run = build_decision_run(ScriptedModel(script), kb, policy, trip, inbox=inbox, memory=memory)
    first = run.start()
    print("run 1 state:", first.state)
    print("decision card:", json.dumps(first.card.to_dict() if first.card else None, indent=1))
    print("rider answers: yes (scripted)")
    resumed = run.resume(True)
    print("run 1 resumed state:", resumed.state)
    print("plan:", resumed.plan.model_dump_json() if resumed.plan else None)

    run2 = build_decision_run(ScriptedModel(script), kb, policy, trip, inbox=inbox, memory=memory)
    second = run2.start()
    raised = run2.handler.count(tracing.INTERRUPT_RAISED)
    print("run 2 (same case) state:", second.state, "| interrupts raised:", raised)
    if exporter is not None:
        print("\n== span events ==")
        print(tracing.render_events(tracing.collect_events(exporter)))
    return 0
