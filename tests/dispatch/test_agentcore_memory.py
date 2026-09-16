"""AgentCore Memory as the durable store for the rider's decisions: every call validated against the service
model as it is made, a decision surviving a session that never took it, the plan well formed."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json

import pytest
from le_dispatch import tracing
from le_dispatch.agentcore_memory import (
    AgentCoreDecisionStore,
    AgentCoreSentStore,
    FakeMemoryClient,
    create_event_params,
    list_events_params,
    memory_plan,
    render_plan,
)
from le_dispatch.api_shapes import check_calls, service_models_available, validate_call
from le_dispatch.interfaces import ROOT, Trip
from le_dispatch.interrupts import DecisionMemory, Inbox, build_decision_run
from le_dispatch.messages import composed_plan
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call

DARK = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=("DELN-E1",), after_dark=True)


def _clock():
    t = [dt.datetime(2026, 9, 13, 3, 0, tzinfo=dt.UTC)]

    def now():
        t[0] += dt.timedelta(seconds=1)
        return t[0]

    return now


def test_the_store_writes_one_event_per_decision_and_the_newest_wins():
    client = FakeMemoryClient()
    store = AgentCoreDecisionStore(client, "mem-0123456789abcdef", "rider-1", clock=_clock())
    assert store.get("DELN-E1") is None
    store.set("DELN-E1", True)
    store.set("EMBR-E3", False)
    store.set("DELN-E1", False)  # the rider changed their mind: the newest event wins
    assert store.get("DELN-E1") is False and store.get("EMBR-E3") is False
    assert store.items() == {"DELN-E1": False, "EMBR-E3": False}
    other = AgentCoreDecisionStore(client, "mem-0123456789abcdef", "rider-2", clock=_clock())
    assert other.get("DELN-E1") is None and other.items() == {}  # one actor per rider
    assert [op for op, _ in client.calls][:3] == ["list_events", "create_event", "create_event"]


@pytest.mark.skipif(not service_models_available(), reason="botocore without the AgentCore models")
def test_every_call_the_store_makes_is_well_formed():
    when = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
    params = create_event_params("mem-0123456789ab", "r", "DELN-E1", {"answer": True}, when)
    assert validate_call("bedrock-agentcore", "create_event", params) is None
    sent = create_event_params("mem-0123456789ab", "r", "DELN-E1", {"entry": {"state": "sent"}}, when, kind="sent")
    assert validate_call("bedrock-agentcore", "create_event", sent) is None
    assert (
        validate_call("bedrock-agentcore", "list_events", list_events_params("mem-0123456789ab", "r", "DELN-E1"))
        is None
    )
    assert validate_call("bedrock-agentcore", "list_events", list_events_params("mem-0123456789ab", "r")) is None
    assert check_calls(memory_plan()["calls"]) == []
    with pytest.raises(ValueError):  # the fake client refuses what the service would refuse
        FakeMemoryClient().create_event(memoryId="mem-0123456789ab", actorId="r", payload=[])


def test_the_plan_names_the_retention_rule_and_the_indexed_key():
    plan = memory_plan(retention_days=30)
    _service, operation, params = plan["calls"][0]
    assert operation == "create_memory" and params["eventExpiryDuration"] == 30
    assert {k["key"] for k in params["indexedKeys"]} == {"case_key", "kind"}
    text = render_plan(plan)
    assert "nothing below has been executed" in text and "LAST_ELEVATOR_MEMORY_ID" in text


def test_a_decision_survives_a_session_that_never_took_it(tmp_path):
    """Session one asks and stores the answer through to the Memory; session two (a fresh agent, an empty
    mirror, no Strands session) finds it there and never asks."""
    from le_dispatch.interfaces import fixture_policy

    kb, policy = fixture_policy()
    client = FakeMemoryClient()
    d = policy(DARK)
    good = {"station": d.station, "elevator": d.elevator, "option": d.top_option}
    script = lambda: [tool_call("draft_plan", good, "t1"), plan_call(composed_plan(d), "p1")]  # noqa: E731

    store1 = AgentCoreDecisionStore(client, "mem-0123456789ab", DARK.rider_id, clock=_clock())
    memory1 = DecisionMemory(tmp_path / "one.json", store=store1)
    run1 = build_decision_run(
        ScriptedModel(script()), kb, policy, DARK, inbox=Inbox(tmp_path / "in1.json"), memory=memory1
    )
    assert run1.start().state == "pending"
    assert run1.resume(True).state == "sent"
    assert store1.get(DARK.case_key) is True  # written through

    store2 = AgentCoreDecisionStore(client, "mem-0123456789ab", DARK.rider_id, clock=_clock())
    memory2 = DecisionMemory(tmp_path / "two.json", store=store2)  # an empty mirror: another machine
    run2 = build_decision_run(
        ScriptedModel(script()), kb, policy, DARK, inbox=Inbox(tmp_path / "in2.json"), memory=memory2
    )
    out = run2.start()
    assert out.state == "sent" and run2.handler.count(tracing.INTERRUPT_RAISED) == 0  # never asked twice
    assert json.loads((tmp_path / "two.json").read_text()) == {DARK.case_key: True}  # cached in the mirror
    without = DecisionMemory(tmp_path / "three.json")  # no store: the same case asks again
    run3 = build_decision_run(
        ScriptedModel(script()), kb, policy, DARK, inbox=Inbox(tmp_path / "in3.json"), memory=without
    )
    assert run3.start().state == "pending"


def test_the_runtime_takes_a_store_factory_and_reads_the_memory_id_from_the_environment(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "entrypoint_memory", ROOT / "infra" / "agentcore" / "runtime" / "entrypoint.py"
    )
    ep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ep)
    monkeypatch.delenv(ep.MEMORY_ID_ENV, raising=False)
    assert ep.decision_store_factory() is None
    monkeypatch.setenv(ep.MEMORY_ID_ENV, "mem-0123456789ab")
    assert callable(ep.decision_store_factory())  # boto3 is imported only when a store is made
    from le_dispatch.interfaces import fixture_policy

    kb, policy = fixture_policy()
    client = FakeMemoryClient()
    stores = {}

    clock = _clock()

    def factory(trip):
        stores[trip.rider_id] = ep.MemoryStores(
            AgentCoreDecisionStore(client, "mem-0123456789ab", trip.rider_id, clock=clock),
            AgentCoreSentStore(client, "mem-0123456789ab", trip.rider_id, clock=clock),
        )
        return stores[trip.rider_id]

    from le_dispatch.bedrock_wire import wired_learner_model

    def model_factory(trip, decision):  # a model that reads the conversation, through the real adapter
        return wired_learner_model("us.amazon.nova-lite-v1:0")

    common = dict(model_factory=model_factory, kb=kb, policy=policy, data_dir=tmp_path, decision_store_factory=factory)
    dark = {"rider_id": "r7", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True}
    assert ep.handle(dark, **common)["state"] == "pending"
    assert ep.handle({**dark, "answer": True}, **common)["state"] == "sent"
    assert stores["r7"].decisions.get(Trip("r7", "DELN", "EMBR", ("DELN-E1",)).case_key) is True
    # a fresh data dir (another runtime session) with the same Memory: no question, and the delivery is
    # already on file there, so the fresh session reports already_sent and runs no model
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    out = ep.handle(dark, **{**common, "data_dir": fresh})
    assert out["state"] == "already_sent" and out["delivered_state"] == "sent"
    # the elevator comes back: the fresh session clears the durable copy; the next outage is a new question
    assert ep.handle({**dark, "outages": []}, **{**common, "data_dir": fresh})["state"] == "quiet"
    later = tmp_path / "later"
    later.mkdir()
    again = ep.handle(dark, **{**common, "data_dir": later})
    assert again["state"] == "pending" and again["gate_counts"]["interrupts"] == 1  # a new outage, a new question
    assert stores["r7"].decisions.get(Trip("r7", "DELN", "EMBR", ("DELN-E1",)).case_key) is None  # cleared event
    assert ep.handle({**dark, "answer": True}, **{**common, "data_dir": later})["state"] == "sent"
    assert ep.handle(dark, **{**common, "data_dir": later})["state"] == "already_sent"


def test_the_sent_log_durable_copy_stops_a_fresh_session_from_sending_twice(tmp_path):
    """Session one delivers and records; session two (a fresh sent log) finds the delivery in the Memory and
    reports already_sent without running a model; the outage ends and a later outage is a new message."""
    from le_dispatch.agentcore_memory import AgentCoreSentStore
    from le_dispatch.interrupts import SentLog

    client = FakeMemoryClient()
    clock = _clock()  # one clock across the sessions, as the wall clock is
    trip = Trip("r9", "DELN", "EMBR", ("DELN-E1",))
    one = SentLog(tmp_path / "one.json", store=AgentCoreSentStore(client, "mem-0123456789ab", "r9", clock=clock))
    assert one.get(trip.case_key) is None
    one.record(trip.case_key, {"option": "alternate_elevator"}, "sent")
    two = SentLog(tmp_path / "two.json", store=AgentCoreSentStore(client, "mem-0123456789ab", "r9", clock=clock))
    assert two.get(trip.case_key)["state"] == "sent"  # delivered by another session
    assert json.loads((tmp_path / "two.json").read_text())[trip.case_key]["state"] == "sent"  # cached
    back = Trip("r9", "DELN", "EMBR", ())  # the elevator is back
    assert trip.case_key in two.clear_stale(back)
    three = SentLog(tmp_path / "three.json", store=AgentCoreSentStore(client, "mem-0123456789ab", "r9", clock=clock))
    assert three.get(trip.case_key) is None  # cleared in the Memory too
    other = SentLog(tmp_path / "o.json", store=AgentCoreSentStore(client, "mem-0123456789ab", "r10", clock=_clock()))
    assert other.get(trip.case_key) is None  # one actor per rider


def test_an_open_question_survives_a_recycled_runtime_session_without_being_asked_again(tmp_path):
    """Session one asks (a card, pending) and is recycled before the rider answers; session two, with the
    same Memory, finds the open card and reports pending without a second interrupt; the rider's answer in
    session two ends the run (the paused run is gone with the old session, so the answer is remembered and
    the model drafts the plan afresh under it, no second question); a third session reports already_sent,
    and so does a second tap on the answer."""
    import importlib.util

    from le_dispatch.agentcore_memory import AgentCoreCardStore
    from le_dispatch.bedrock_wire import wired_learner_model
    from le_dispatch.interfaces import fixture_policy

    spec = importlib.util.spec_from_file_location(
        "entrypoint_cards", ROOT / "infra" / "agentcore" / "runtime" / "entrypoint.py"
    )
    ep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ep)
    kb, policy = fixture_policy()
    client = FakeMemoryClient()
    clock = _clock()

    def factory(trip):
        return ep.MemoryStores(
            AgentCoreDecisionStore(client, "mem-0123456789ab", trip.rider_id, clock=clock),
            AgentCoreSentStore(client, "mem-0123456789ab", trip.rider_id, clock=clock),
            AgentCoreCardStore(client, "mem-0123456789ab", trip.rider_id, clock=clock),
        )

    def model_factory(trip, decision):
        return wired_learner_model("us.amazon.nova-lite-v1:0")

    common = dict(model_factory=model_factory, kb=kb, policy=policy, decision_store_factory=factory)
    dark = {"rider_id": "r8", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True}
    one, two, three = tmp_path / "one", tmp_path / "two", tmp_path / "three"
    for d in (one, two, three):
        d.mkdir()
    first = ep.handle(dark, **common, data_dir=one)
    assert first["state"] == "pending"
    assert sum(1 for op, _ in client.calls if op == "create_event") >= 1  # the card, written through
    second = ep.handle(dark, **common, data_dir=two)  # a recycled session: the question is still open
    assert second["state"] == "pending" and second["card"]["case_key"] == first["card"]["case_key"]
    assert set(second["gate_counts"].values()) == {0}  # no model ran, no new interrupt
    answered = ep.handle({**dark, "answer": True}, **common, data_dir=two)
    assert answered["state"] == "sent" and answered["plan"]["option"] == policy(ep.trip_from(dark)).top_option
    assert answered["composed_by"] == "model"  # no paused run to resume: a fresh run under the remembered answer
    assert answered["gate_counts"]["interrupts"] == 0 and answered["card"]["answer"] is True
    assert ep.handle(dark, **common, data_dir=three)["state"] == "already_sent"
    again = ep.handle({**dark, "answer": True}, **common, data_dir=three)  # the double tap
    assert again["state"] == "already_sent" and again["delivered_state"] == "sent"
    back = ep.handle({**dark, "outages": []}, **common, data_dir=three)
    assert back["state"] == "quiet"


def test_the_store_follows_pages():
    client = FakeMemoryClient(page_size=2)
    store = AgentCoreDecisionStore(client, "mem-0123456789ab", "rider-1", clock=_clock())
    for i in range(5):
        store.set(f"case-{i}", i % 2 == 0)
    assert store.items() == {f"case-{i}": (i % 2 == 0) for i in range(5)}
    assert store.get("case-4") is True and store.get("case-3") is False
    pages = [p for op, p in client.calls if op == "list_events" and p.get("nextToken")]
    assert pages, "the second page was fetched with the token"


class _Flaky(FakeMemoryClient):
    """The fake client with a switch: down, every call raises what the service raises."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.down = False

    def _raise(self, operation: str):
        from botocore.exceptions import ClientError

        raise ClientError({"Error": {"Code": "ThrottledException", "Message": "slow down"}}, operation)

    def create_event(self, **params):
        if self.down:
            self._raise("CreateEvent")
        return super().create_event(**params)

    def list_events(self, **params):
        if self.down:
            self._raise("ListEvents")
        return super().list_events(**params)


def test_a_memory_outage_never_fails_an_invocation_and_the_backlog_replays(tmp_path):
    """Memory down for two polls: a plan already sent is answered from the session's copy (already_sent),
    a new rider's outage is still delivered (sent) with the write kept; Memory back: the next invocation
    replays the backlog before its own call, and the durable copy has every event, none twice. Every
    response says what the durable copy's state was; the trace carries memory.degraded and memory.replayed."""
    import importlib.util

    from le_dispatch.bedrock_wire import wired_learner_model
    from le_dispatch.interfaces import fixture_policy

    spec = importlib.util.spec_from_file_location(
        "entrypoint_outage", ROOT / "infra" / "agentcore" / "runtime" / "entrypoint.py"
    )
    ep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ep)
    kb, policy = fixture_policy()
    flaky = _Flaky()
    factory = ep.decision_store_factory("mem-0123456789ab", "us-west-2", client=flaky)  # one client per container
    exporter = tracing.memory_exporter()
    exporter.clear()

    def model_factory(trip, decision):
        return wired_learner_model("us.amazon.nova-lite-v1:0")

    common = dict(model_factory=model_factory, kb=kb, policy=policy, decision_store_factory=factory, data_dir=tmp_path)
    day = {"rider_id": "r20", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}
    first = ep.handle(day, **common)
    assert first["state"] == "sent" and first["memory"]["status"] == "ok"
    events_before = len(flaky.events)

    flaky.down = True
    repeat = ep.handle(day, **common)  # the read for the open cards fails; the session's sent log answers
    assert repeat["state"] == "already_sent" and repeat["memory"]["status"] == "degraded"
    assert repeat["memory"]["reason"] == "list_events: ThrottledException"
    other = ep.handle({**day, "rider_id": "r21"}, **common)  # a delivery while Memory is down
    assert other["state"] == "sent" and other["composed_by"] == "model"
    assert other["memory"]["status"] == "degraded" and other["memory"]["backlog"] >= 1
    assert len(flaky.events) == events_before  # nothing reached the durable copy while it was down
    backlog = other["memory"]["backlog"]

    flaky.down = False
    back = ep.handle({**day, "rider_id": "r21"}, **common)  # the next invocation: the backlog goes first
    assert back["state"] == "already_sent" and back["memory"]["status"] == "ok"
    assert back["memory"]["backlog"] == 0 and back["memory"]["replayed"] == backlog
    assert len(flaky.events) == events_before + backlog
    tokens = [e.get("clientToken") for e in flaky.events]
    assert len(tokens) == len(set(tokens)) and all(tokens)  # every write carries its token, none stored twice
    names = [e["event"] for e in tracing.collect_events(exporter)]
    assert tracing.MEMORY_DEGRADED in names and tracing.MEMORY_REPLAYED in names
    # a fresh session for r21 finds the delivery in the durable copy: one outage, one message, across sessions
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert ep.handle({**day, "rider_id": "r21"}, **{**common, "data_dir": fresh})["state"] == "already_sent"


def test_a_replay_or_a_retry_of_the_same_write_is_stored_once():
    """The client token is derived from the write (memory, actor, case, kind, content, timestamp): the same
    event sent twice is one event; a different timestamp is a different event."""
    client = FakeMemoryClient()
    clock = _clock()
    store = AgentCoreDecisionStore(client, "mem-0123456789ab", "rider-1", clock=clock)
    when = clock()
    params = create_event_params("mem-0123456789ab", "rider-1", "case-1", {"answer": True}, when)
    again = create_event_params("mem-0123456789ab", "rider-1", "case-1", {"answer": True}, when)
    assert params["clientToken"] == again["clientToken"] and len(params["clientToken"]) == 64
    client.create_event(**params)
    client.create_event(**again)
    assert len(client.events) == 1
    store.set("case-1", False)  # a later write, another timestamp: a second event, and the newest wins
    assert len(client.events) == 2 and store.get("case-1") is False
    assert not check_calls([("bedrock-agentcore", "create_event", params)]) or not service_models_available()


def test_the_resilient_client_keeps_order_and_stops_at_the_first_failure_on_replay():
    from le_dispatch.agentcore_memory import ResilientMemoryClient

    flaky = _Flaky()
    resilient = ResilientMemoryClient(flaky)
    clock = _clock()
    store = AgentCoreSentStore(resilient, "mem-0123456789ab", "rider-1", clock=clock)
    flaky.down = True
    store.record("case-1", {"state": "sent", "plan": {"option": "a"}})
    store.record("case-2", {"state": "sent", "plan": {"option": "b"}})
    assert resilient.status["backlog"] == 2 and resilient.status["status"] == "degraded"
    assert store.get("case-1") is None  # unknown while down: the caller keeps its own copy
    assert resilient.status["failures"] >= 3
    flaky.down = False
    assert store.get("case-2") is not None  # the read replays the backlog first, then answers
    assert [e["metadata"]["case_key"]["stringValue"] for e in flaky.events] == ["case-1", "case-2"]  # in order
    assert resilient.status == {
        "status": "ok",
        "reason": None,
        "backlog": 0,
        "replayed": 2,
        "failures": resilient.failures,
    }
