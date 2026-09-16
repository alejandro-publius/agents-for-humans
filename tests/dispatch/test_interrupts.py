"""F2: Interrupt for after-dark and last-train decisions, with a scripted human."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC

import pytest
from le_dispatch import tracing
from le_dispatch.interfaces import Trip
from le_dispatch.interrupts import DecisionMemory, Inbox, build_decision_run, needs_human
from le_dispatch.messages import composed_plan
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call

DARK = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=("DELN-E1",), after_dark=True)
LAST = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=("DELN-E1",), last_train=True)
DAY = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=("DELN-E1",))


def plan_for(policy, trip, **overrides):
    d = policy(trip)
    p = composed_plan(d, overrides.get("status", "send"))
    p.update(overrides)
    return p


def compliant_script(policy, trip, final_status="send"):
    d = policy(trip)
    return [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        plan_call(plan_for(policy, trip, status=final_status), "p1"),
    ]


@pytest.fixture
def stores(tmp_path):
    return Inbox(tmp_path / "inbox.json"), DecisionMemory(tmp_path / "decisions.json")


@pytest.mark.parametrize("trip", [DARK, LAST], ids=["after_dark", "last_train"])
def test_run_pauses_writes_card_and_resumes_on_yes(fixture_stack, stores, trip):
    kb, policy = fixture_stack
    inbox, memory = stores
    d = policy(trip)
    model = ScriptedModel(compliant_script(policy, trip))
    run = build_decision_run(model, kb, policy, trip, inbox=inbox, memory=memory)

    first = run.start()
    assert first.state == "pending" and first.interrupt_ids
    card = first.card
    assert card is not None and card.answer is None
    assert card.option == d.top_option
    assert card.added_minutes == d.minutes_for(d.top_option)
    assert card.flags == d.flags and any(card.flags.values())
    assert card.source_url == d.source_url and card.source_url.startswith("https://www.bart.gov/")
    assert [r["label"] for r in card.rejected] == [o.label for o in d.rejected()]
    assert all(r["reason"] for r in card.rejected)
    assert inbox.pending("r1")[0].case_key == trip.case_key
    assert run.handler.count(tracing.INTERRUPT_RAISED) == 1

    resumed = run.resume(True)
    assert resumed.state == "sent"
    assert resumed.plan.option == d.top_option and resumed.plan.status == "send"
    assert inbox.pending("r1") == [] and inbox.get(trip.case_key).answer is True
    assert memory.get(trip.case_key) is True
    assert run.bundle.agent.state.get("last_elevator.decisions") == {trip.case_key: True}
    assert run.handler.count(tracing.INTERRUPT_RESUMED) == 1


def test_same_case_does_not_interrupt_again(fixture_stack, stores):
    kb, policy = fixture_stack
    inbox, memory = stores
    model = ScriptedModel(compliant_script(policy, DARK))
    run = build_decision_run(model, kb, policy, DARK, inbox=inbox, memory=memory)
    run.start()
    run.resume(True)

    # a fresh process: memory comes back from the JSON mirror, then agent.state
    memory2 = DecisionMemory(memory.path)
    run2 = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)), kb, policy, DARK, inbox=inbox, memory=memory2
    )
    second = run2.start()
    assert second.state == "sent"
    assert run2.handler.count(tracing.INTERRUPT_RAISED) == 0
    assert inbox.pending("r1") == []


def test_decline_cancels_tool_and_holds_plan(fixture_stack, stores):
    kb, policy = fixture_stack
    inbox, memory = stores
    d = policy(DARK)
    script = [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        plan_call(plan_for(policy, DARK, status="send"), "p1"),  # ignores the decline: Guided
        plan_call(plan_for(policy, DARK, status="hold"), "p2"),
    ]
    run = build_decision_run(ScriptedModel(script), kb, policy, DARK, inbox=inbox, memory=memory)
    assert run.start().state == "pending"
    held = run.resume(False)
    assert held.state == "held" and held.plan.status == "hold"
    assert held.plan.option == d.top_option  # BART's option stays on file, unchanged by the model
    assert run.handler.count(tracing.GUIDE_AFTER) == 1
    assert memory.get(DARK.case_key) is False
    denied = [
        b["toolResult"]
        for m in run.bundle.agent.messages
        for b in m["content"]
        if "toolResult" in b and b["toolResult"]["status"] == "error"
    ]
    assert denied and "Manual approval denied" in json.dumps(denied[0])

    # next time: no interrupt, draft_plan is guided away, the hold plan is accepted
    script2 = [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        plan_call(plan_for(policy, DARK, status="hold"), "p1"),
    ]
    run2 = build_decision_run(ScriptedModel(script2), kb, policy, DARK, inbox=inbox, memory=memory)
    again = run2.start()
    assert again.state == "held"
    assert run2.handler.count(tracing.INTERRUPT_RAISED) == 0
    assert run2.handler.count(tracing.GUIDE_BEFORE) == 1


def test_daytime_case_never_interrupts(fixture_stack, stores):
    kb, policy = fixture_stack
    inbox, memory = stores
    assert not needs_human(policy(DAY))
    model = ScriptedModel(compliant_script(policy, DAY))
    run = build_decision_run(model, kb, policy, DAY, inbox=inbox, memory=memory)
    out = run.start()
    assert out.state == "sent" and out.card is None
    assert inbox.pending() == []
    with pytest.raises(RuntimeError):
        run.resume(True)


def test_model_cannot_hold_without_the_rider(fixture_stack, stores):
    kb, policy = fixture_stack
    inbox, memory = stores
    d = policy(DARK)
    script = [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        plan_call(plan_for(policy, DARK, status="hold"), "p1"),  # rider said yes: Guided
        plan_call(plan_for(policy, DARK, status="send"), "p2"),
    ]
    run = build_decision_run(ScriptedModel(script), kb, policy, DARK, inbox=inbox, memory=memory)
    run.start()
    out = run.resume(True)
    assert out.state == "sent" and run.handler.count(tracing.GUIDE_AFTER) == 1


def test_trace_has_interrupt_events(fixture_stack, stores):
    kb, policy = fixture_stack
    inbox, memory = stores
    exporter = tracing.memory_exporter()
    exporter.clear()
    model = ScriptedModel(compliant_script(policy, DARK))
    run = build_decision_run(model, kb, policy, DARK, inbox=inbox, memory=memory)
    run.start()
    run.resume(True)
    names = [e["event"] for e in tracing.collect_events(exporter)]
    assert tracing.INTERRUPT_RAISED in names
    assert tracing.INTERRUPT_RESUMED in names


def test_pause_and_resume_across_processes_with_file_session_manager(fixture_stack, tmp_path):
    """Process 1 pauses; process 2 (a new agent, new handler, same session id)
    resumes from the inbox card; process 3 never interrupts. Strands'
    FileSessionManager carries the messages, the pending interrupt and
    agent.state (the decision memory) between them."""
    from strands.session.file_session_manager import FileSessionManager

    kb, policy = fixture_stack
    d = policy(DARK)
    inbox, memory = Inbox(tmp_path / "inbox.json"), DecisionMemory(tmp_path / "decisions.json")
    session_id = f"le-{DARK.rider_id}-deln"
    storage = str(tmp_path / "sessions")

    # process 1: the poller finds the outage after dark, the run pauses
    run1 = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)),
        kb,
        policy,
        DARK,
        inbox=inbox,
        memory=memory,
        session_manager=FileSessionManager(session_id=session_id, storage_dir=storage),
    )
    first = run1.start()
    assert first.state == "pending"
    card = inbox.get(DARK.case_key)
    assert card.interrupt_ids and card.answer is None
    del run1

    # process 2: the rider taps yes in the app; a fresh agent resumes from the card
    model2 = ScriptedModel([plan_call(plan_for(policy, DARK), "p1")])  # the tool re-runs from the session, then Plan
    run2 = build_decision_run(
        model2,
        kb,
        policy,
        DARK,
        inbox=inbox,
        memory=DecisionMemory(tmp_path / "decisions.json"),
        session_manager=FileSessionManager(session_id=session_id, storage_dir=storage),
    )
    resumed = run2.resume(True)
    assert resumed.state == "sent" and resumed.plan.option == d.top_option
    assert run2.bundle.agent.state.get("last_elevator.decisions") == {DARK.case_key: True}
    assert inbox.get(DARK.case_key).answer is True

    # process 3: the next poll for the same case finds the decision in the session and never asks
    run3 = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)),
        kb,
        policy,
        DARK,
        inbox=inbox,
        memory=DecisionMemory(),  # no JSON mirror: only the session's agent.state knows
        session_manager=FileSessionManager(session_id=session_id, storage_dir=storage),
    )
    assert run3.handler.memory.get(DARK.case_key) is True
    third = run3.resume(True)  # an answer with nothing pending never fails: the plan is drafted under it
    assert third.state == "sent" and third.composed_by == "model" and run3.handler.count(tracing.INTERRUPT_RAISED) == 0


def test_the_memory_forgets_a_decision_when_its_outage_ends_in_every_copy(fixture_stack, tmp_path):
    """clear_stale drops the answer from the mirror, the session's copy and the durable store (a cleared
    event); a tombstone keeps the session's stale copy from coming back on attach; a new answer spends it."""
    from le_dispatch.agentcore_memory import AgentCoreDecisionStore, FakeMemoryClient

    store = AgentCoreDecisionStore(FakeMemoryClient(), "mem-0123456789ab", "r1")
    memory = DecisionMemory(tmp_path / "d.json", store=store)
    memory.set(DARK.case_key, False)
    memory.set("r1|DELN>EMBR|DELN-E2", True)  # another elevator, still out below
    assert store.get(DARK.case_key) is False
    back = replace(DARK, outages=("DELN-E2",))
    assert memory.clear_stale(back) == [DARK.case_key]
    assert memory.get(DARK.case_key) is None and memory.get("r1|DELN>EMBR|DELN-E2") is True
    assert store.get(DARK.case_key) is None and store.get("r1|DELN>EMBR|DELN-E2") is True
    assert json.loads(memory.tombstones_path.read_text()) == [DARK.case_key]
    # a session whose state still carries the old answer: attach drops it
    from strands import Agent

    agent = Agent(model=ScriptedModel([]), callback_handler=None)
    agent.state.set("last_elevator.decisions", {DARK.case_key: False, "r1|DELN>EMBR|DELN-E2": True})
    fresh = DecisionMemory(tmp_path / "d.json", store=store)
    fresh.attach(agent)
    assert agent.state.get("last_elevator.decisions") == {"r1|DELN>EMBR|DELN-E2": True}
    # without a mirror on disk but with the store: the store's cleared event is what drops it
    agent2 = Agent(model=ScriptedModel([]), callback_handler=None)
    agent2.state.set("last_elevator.decisions", {DARK.case_key: False})
    DecisionMemory(store=store).attach(agent2)
    assert agent2.state.get("last_elevator.decisions") == {}
    # a new outage's answer spends the tombstone
    fresh.set(DARK.case_key, True)
    assert json.loads(fresh.tombstones_path.read_text()) == [] and fresh.get(DARK.case_key) is True


def test_pending_case_is_not_asked_again_on_the_next_poll(fixture_stack, stores):
    """Five minutes later the poller sees the same outage; the rider has not
    answered yet. The run reports pending from the inbox and raises no new
    interrupt, so the quiet metric counts one question, not one per poll."""
    kb, policy = fixture_stack
    inbox, memory = stores
    run1 = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)), kb, policy, DARK, inbox=inbox, memory=memory
    )
    first = run1.start()
    assert first.state == "pending"
    run2 = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)), kb, policy, DARK, inbox=inbox, memory=memory
    )
    again = run2.start()
    assert again.state == "pending" and again.interrupt_ids == first.interrupt_ids
    assert run2.handler.count(tracing.INTERRUPT_RAISED) == 0
    assert run2.bundle.agent.model.calls == 0  # the agent was not even invoked
    assert len(inbox.pending("r1")) == 1


def test_card_question_is_in_plain_words(fixture_stack):
    """A screen reader reads the card: no labels with underscores, the flags as sentences, the minutes."""
    from le_dispatch.interrupts import card_question

    kb, policy = fixture_stack
    dark = card_question(policy(DARK))
    assert dark.startswith("It is after dark. DELN elevator DELN-E1 is out at your starting station. ")
    assert "BART's option is the alternate elevator" in dark
    assert "_" not in dark and dark.endswith("about 4 minutes more. Send this plan now?")
    last = card_question(policy(LAST))
    assert last.startswith("This is the last train.") and "after dark" not in last
    both = card_question(policy(Trip("r1", "DELN", "EMBR", ("DELN-E1",), after_dark=True, last_train=True)))
    assert both.startswith("It is after dark. This is the last train.")


def test_station_names_reach_every_sentence_and_the_card_when_the_kb_has_them():
    """A KB with station_names: the approved sentences, the hold sentences and the card say the name a rider
    hears, the gate still accepts exactly those sentences, and the fixture KB (no names) is unchanged."""
    from le_dispatch.gates import build_agent, deliver
    from le_dispatch.interrupts import card_question
    from le_dispatch.messages import approved_messages, hold_messages, is_approved
    from le_dispatch.portability import kb_json, synthetic_agency

    kb, cases, policy = synthetic_agency()
    assert kb.name_of("ATN0") == "A Town" and kb.name_of("ZZZZ") == "ZZZZ" and kb.name_of(None) == ""
    assert kb_json(kb)["station_names"]["ATN0"] == "A Town"
    c = cases[0]
    trip = Trip("r", c.station, "BTN1", (c.elevator,), after_dark=True)
    d = policy(trip)
    assert d.station == "ATN0" and d.spoken_station == "A Town"
    assert all("A Town" in m and "ATN0 elevator" not in m for m in approved_messages(d) + hold_messages(d))
    assert card_question(d).startswith("It is after dark. A Town elevator ATN0-E1 is out at your starting station.")
    good = composed_plan(d)
    del good["status"]
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
            plan_call({**good, "rider_message": good["rider_message"].replace("A Town", "ATN0")}, "p1"),  # the code
            plan_call(good, "p2"),  # the name
        ]
    )
    bundle = build_agent(model, kb, policy, Trip("r", c.station, "BTN1", (c.elevator,)))
    out = deliver(bundle)
    assert out.composed_by == "model" and "A Town" in out.plan["rider_message"] and model.calls == 3
    assert not is_approved(good["rider_message"].replace("A Town", "ATN0"), d)


def test_open_question_is_withdrawn_when_the_elevator_comes_back(fixture_stack, stores):
    """The question must not outlive the outage: the next poll with the elevator back closes the card,
    pending() no longer lists it, a late answer is refused, and a new outage asks afresh."""
    kb, policy = fixture_stack
    inbox, memory = stores
    run = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)), kb, policy, DARK, inbox=inbox, memory=memory
    )
    assert run.start().state == "pending" and len(inbox.pending("r1")) == 1

    back = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=(), after_dark=True)
    assert policy(back).affected is False
    withdrawn = inbox.withdraw_stale(back)
    assert withdrawn == [DARK.case_key]
    card = inbox.get(DARK.case_key)
    assert card.withdrawn_at and "back in service" in card.withdrawn_reason and card.answer is None
    assert inbox.pending("r1") == [] and not card.open
    assert inbox.withdraw_stale(back) == []  # idempotent

    late = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)), kb, policy, DARK, inbox=inbox, memory=memory
    )
    with pytest.raises(RuntimeError, match="withdrawn"):
        late.resume(True)
    assert memory.get(DARK.case_key) is None  # a withdrawn question never becomes a remembered decision

    # the same elevator goes out again later: the rider is asked afresh (the withdrawn card is replaced)
    again = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)), kb, policy, DARK, inbox=inbox, memory=memory
    )
    assert again.start().state == "pending" and again.handler.count(tracing.INTERRUPT_RAISED) == 1
    assert inbox.get(DARK.case_key).open

    # another rider's or another trip's cards are untouched
    other = Trip(rider_id="r2", origin="DELN", destination="EMBR", outages=("DELN-E1",), after_dark=True)
    other_run = build_decision_run(
        ScriptedModel(compliant_script(policy, other)), kb, policy, other, inbox=inbox, memory=DecisionMemory()
    )
    assert other_run.start().state == "pending"
    assert inbox.withdraw_stale(back) == [DARK.case_key] and inbox.get(other.case_key).open


def test_inbox_writes_are_atomic_and_serialized_across_threads(tmp_path):
    """The poller writes cards while the app answers: 8 threads, 40 operations each, on one inbox; every
    card and every answer survives, and no reader ever sees a torn file."""
    import threading

    from le_dispatch.interrupts import DecisionCard

    inbox = Inbox(tmp_path / "inbox.json")
    errors: list[BaseException] = []

    def card(i: int) -> DecisionCard:
        return DecisionCard(
            case_key=f"r{i % 8}|DELN>EMBR|DELN-E{i}",
            rider_id=f"r{i % 8}",
            station="DELN",
            elevator=f"DELN-E{i}",
            option="alternate_elevator",
            added_minutes=4,
            flags={"after_dark": True},
            source_url="",
            rejected=[],
            question="?",
        )

    def worker(t: int) -> None:
        try:
            for k in range(40):
                i = t * 40 + k
                inbox.write(card(i))
                inbox.set_interrupts(card(i).case_key, [f"int-{i}"])
                if k % 2:
                    inbox.answer(card(i).case_key, True)
                inbox.pending()  # a concurrent reader
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    cards = {c.case_key: c for c in (DecisionCard(**c) for c in inbox._load())}
    assert len(cards) == 320
    assert all(c.interrupt_ids == [f"int-{c.elevator[6:]}"] for c in cards.values())
    assert sum(1 for c in cards.values() if c.answer is True) == 160 and len(inbox.pending()) == 160
    assert not list(tmp_path.glob("*.tmp"))  # no temporary file left behind


def test_retention_drops_only_closed_cards_older_than_the_rule(tmp_path, capsys):
    """Answered and withdrawn cards older than N days go; open cards never do; the script is a dry run
    unless --yes, and it lists stale evidence packets under the data dir."""
    import importlib.util
    import os
    import sys
    from datetime import datetime, timedelta

    from le_dispatch.interfaces import ROOT
    from le_dispatch.interrupts import DecisionCard

    inbox = Inbox(tmp_path / "inbox.json")
    now = datetime.now(UTC)
    old = (now - timedelta(days=40)).isoformat(timespec="seconds")
    recent = (now - timedelta(days=2)).isoformat(timespec="seconds")

    def card(key: str, **kw) -> DecisionCard:
        return DecisionCard(
            case_key=key,
            rider_id="r1",
            station="DELN",
            elevator="DELN-E1",
            option="alternate_elevator",
            added_minutes=4,
            flags={},
            source_url="",
            rejected=[],
            question="?",
            **kw,
        )

    inbox.write(card("old-answered", answer=True, answered_at=old))
    inbox.write(card("old-withdrawn", withdrawn_at=old, withdrawn_reason="back"))
    inbox.write(card("recent-answered", answer=False, answered_at=recent))
    inbox.write(card("old-open", created_at=old))  # open: never purged
    assert inbox.purge(older_than_days=30, now=now) == ["old-answered", "old-withdrawn"]
    assert {c["case_key"] for c in inbox._load()} == {"recent-answered", "old-open"}
    assert inbox.purge(older_than_days=30, now=now) == []

    # the script: dry run by default, --yes applies, stale packets listed
    inbox.write(card("old-answered-2", answer=True, answered_at=old))
    packets = tmp_path / "evidence"
    packets.mkdir()
    stale = packets / "live-old.md"
    stale.write_text("x")
    os.utime(stale, (now.timestamp() - 45 * 86400,) * 2)
    fresh = packets / "live-new.md"
    fresh.write_text("y")
    spec = importlib.util.spec_from_file_location("retention", ROOT / "scripts" / "retention.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["retention"] = module
    spec.loader.exec_module(module)
    assert module.main(["--data-dir", str(tmp_path), "--days", "30"]) == 0
    out = capsys.readouterr().out
    assert "would drop 1 closed card(s)" in out and "card old-answered-2" in out and "packet live-old.md" in out
    assert stale.exists() and len(inbox._load()) == 3
    assert module.main(["--data-dir", str(tmp_path), "--days", "30", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "dropped 1 closed card(s)" in out
    assert (
        not stale.exists()
        and fresh.exists()
        and {c["case_key"] for c in inbox._load()} == {"recent-answered", "old-open"}
    )


def test_decision_run_rechecks_the_plan_even_if_the_gate_never_fired(fixture_stack, stores, monkeypatch):
    """The same last line as deliver(), on the human-moment path: with the after-model gate silenced and a
    wrong plan after the rider's yes, code composes the plan instead."""
    from le_dispatch.gates import PlanGateHandler
    from strands.vended_plugins.steering.core.action import Proceed

    kb, policy = fixture_stack
    inbox, memory = stores
    d = policy(DARK)

    async def never_fires(self, *, agent, message, stop_reason, **kwargs):
        return Proceed(reason="simulated: the after-model hook was not invoked")

    monkeypatch.setattr(PlanGateHandler, "steer_after_model", never_fires)
    wrong = plan_for(policy, DARK, option="transit", added_minutes=1)
    script = [
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
        plan_call(wrong, "p1"),
    ]
    run = build_decision_run(ScriptedModel(script), kb, policy, DARK, inbox=inbox, memory=memory)
    assert run.start().state == "pending"
    out = run.resume(True)
    assert out.state == "sent" and out.composed_by == "code"
    assert out.plan.option == d.top_option and out.plan.added_minutes == d.minutes_for(d.top_option)


@pytest.mark.parametrize("answer", [True, False], ids=["yes", "no"])
def test_a_resumed_call_the_gates_retry_does_not_ask_the_rider_again(fixture_stack, stores, answer):
    """The interrupted draft_plan call had the wrong option. On the resumed pass the option gate cancels it
    and the model retries with a new tool use id; that second call must not raise a second interrupt (the
    answer is known), so one resume ends the run: sent on yes, held on no."""
    kb, policy = fixture_stack
    inbox, memory = stores
    d = policy(DARK)
    wrong = next(o.label for o in d.ranked if o.label != d.top_option)
    good = {"station": d.station, "elevator": d.elevator, "option": d.top_option}
    model = ScriptedModel(
        [
            tool_call("draft_plan", {**good, "option": wrong}, "t1"),  # interrupted, then guided on resume
            tool_call("draft_plan", good, "t2"),  # a new tool use id on the resumed pass
            plan_call(plan_for(policy, DARK, status="send" if answer else "hold"), "p1"),
        ]
    )
    run = build_decision_run(model, kb, policy, DARK, inbox=inbox, memory=memory)
    assert run.start().state == "pending"
    out = run.resume(answer)
    assert out.state == ("sent" if answer else "held") and out.composed_by == "model"
    assert run.handler.count(tracing.INTERRUPT_RAISED) == 1 and run.handler.count(tracing.INTERRUPT_RESUMED) == 1
    assert run.bundle.gate.count(tracing.GUIDE_BEFORE) == 2  # the option gate guided the call on both passes
    assert memory.get(DARK.case_key) is answer
    assert inbox.get(DARK.case_key).answer is answer
    with pytest.raises(RuntimeError):
        run.resume(answer)  # nothing left to resume: the rider was asked once


def test_the_default_prompt_names_the_trip_and_the_outage(fixture_stack, stores):
    kb, policy = fixture_stack
    inbox, memory = stores
    run = build_decision_run(
        ScriptedModel(compliant_script(policy, DARK)), kb, policy, DARK, inbox=inbox, memory=memory
    )
    assert "from DELN to EMBR" in run.prompt and "Elevator DELN-E1 at DELN is out" in run.prompt
    assert "approved_messages" in run.prompt
