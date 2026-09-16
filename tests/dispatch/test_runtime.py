"""F15: the AgentCore Runtime entrypoint's payload contract, offline."""

from __future__ import annotations

import importlib.util
import sys

import pytest
from le_dispatch.interfaces import ROOT  # the repo root in either layout (tests/ or tests/dispatch/)
from le_dispatch.messages import composed_plan
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call


def load_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "entrypoint", ROOT / "infra" / "agentcore" / "runtime" / "entrypoint.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["entrypoint"] = mod
    spec.loader.exec_module(mod)
    return mod


def compliant(trip, decision):
    d = decision
    plan = composed_plan(d)
    return ScriptedModel(
        [
            tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t"),
            plan_call(plan, "p"),
        ]
    )


def test_entrypoint_quiet_sent_pending_and_resume(tmp_path):
    ep = load_entrypoint()
    quiet = ep.handle(
        {"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": []},
        model_factory=compliant,
        data_dir=tmp_path,
    )
    assert quiet["state"] == "quiet" and quiet["plan"] is None

    sent = ep.handle(
        {"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]},
        model_factory=compliant,
        data_dir=tmp_path,
    )
    assert sent["state"] == "sent" and sent["plan"]["option"] == "alternate_elevator"
    assert sent["gate_counts"]["interrupts"] == 0

    # for r1 the daytime plan was already sent for this outage, and one outage is one message; r1n meets the
    # outage after dark and is asked
    repeat = ep.handle(
        {"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True},
        model_factory=compliant,
        data_dir=tmp_path,
    )
    assert repeat["state"] == "already_sent"
    dark = {"rider_id": "r1n", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True}
    pending = ep.handle(dark, model_factory=compliant, data_dir=tmp_path)
    assert pending["state"] == "pending" and pending["card"]["question"].endswith("Send this plan now?")
    assert pending["plan"] is None

    # the app posts the answer; a new invocation resumes from the inbox card (same process here; the
    # session manager factory carries it across invocations on the runtime)
    resumed = ep.handle(
        {**dark, "answer": True},
        model_factory=lambda trip, d: ScriptedModel([plan_call(composed_plan(d), "p")]),
        data_dir=tmp_path,
    )
    assert resumed["state"] in ("sent", "held")


def test_make_runtime_needs_the_sdk_only_when_called():
    ep = load_entrypoint()
    pytest.importorskip("bedrock_agentcore")
    app = ep.make_runtime(compliant)
    assert hasattr(app, "run")


def test_agentcore_app_serves_ping_and_invocations_in_process(tmp_path):
    """The real BedrockAgentCoreApp (the bedrock-agentcore SDK) built by make_runtime, driven through
    Starlette's in-memory test client: no socket is opened, so the network guard stays satisfied.
    This is the contract `agentcore invoke` exercises on the deployed runtime."""
    pytest.importorskip("bedrock_agentcore")
    from starlette.testclient import TestClient

    ep = load_entrypoint()
    app = ep.make_runtime(compliant, data_dir=tmp_path)
    with TestClient(app) as client:
        ping = client.get("/ping")
        assert ping.status_code == 200 and ping.json().get("status") in ("Healthy", "HealthyBusy")
        quiet = client.post(
            "/invocations", json={"rider_id": "r9", "origin": "DELN", "destination": "EMBR", "outages": []}
        )
        assert quiet.status_code == 200 and quiet.json()["state"] == "quiet"
        sent = client.post(
            "/invocations", json={"rider_id": "r9", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}
        )
        assert sent.status_code == 200
        body = sent.json()
        assert body["state"] == "sent" and body["plan"]["option"] == "alternate_elevator"
        assert body["plan"]["rider_message"].startswith("DELN elevator DELN-E1 is out at your starting station.")
        again = client.post(
            "/invocations", json={"rider_id": "r9", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}
        )
        assert again.status_code == 200 and again.json()["state"] == "already_sent"  # one outage, one message
        dark = client.post(
            "/invocations",
            json={
                "rider_id": "r9n",
                "origin": "DELN",
                "destination": "EMBR",
                "outages": ["DELN-E1"],
                "after_dark": True,
            },
        )
        assert dark.status_code == 200 and dark.json()["state"] == "pending"


def test_entrypoint_withdraws_an_open_question_when_the_elevator_is_back(tmp_path):
    """Poll 1 after dark: pending. Poll 2 with the elevator back: quiet, and the card is withdrawn so the app
    stops showing the question; a late answer on poll 3 does not resurrect it."""
    ep = load_entrypoint()
    dark = {"rider_id": "r7", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True}
    pending = ep.handle(dark, model_factory=compliant, data_dir=tmp_path)
    assert pending["state"] == "pending" and pending["withdrawn"] == []
    back = ep.handle({**dark, "outages": []}, model_factory=compliant, data_dir=tmp_path)
    assert back["state"] == "quiet" and back["withdrawn"] == ["r7|DELN>EMBR|DELN-E1"]
    from le_dispatch.interrupts import Inbox

    inbox = Inbox(tmp_path / "inbox.json")
    assert inbox.pending("r7") == [] and inbox.get("r7|DELN>EMBR|DELN-E1").withdrawn_at
    # the app posts the rider's late answer against the closed question: state withdrawn, nothing is sent
    late = ep.handle({**dark, "answer": True}, model_factory=compliant, data_dir=tmp_path)
    assert late["state"] == "withdrawn" and late["plan"] is None and late["card"]["withdrawn_at"]


def test_the_morning_after_sends_the_plan_and_closes_the_night_question(tmp_path):
    """Poll 1 after dark: pending (a question). The rider never answers. Poll 2 in daylight with the outage
    still on: the rule that asked no longer holds, so the question is closed as superseded, the paused run
    is released and the plan is sent the way any daytime plan is, without a second question. A late answer
    to the night's question is answered with what was delivered."""
    ep = load_entrypoint()
    from le_dispatch.interrupts import SUPERSEDED_REASON, Inbox

    def morning(trip, decision):  # the released run continues from the tool result: the Plan comes next
        return ScriptedModel([plan_call(composed_plan(decision), "p")])

    night = {"rider_id": "r9", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True}
    day = {**night, "after_dark": False}
    key = "r9|DELN>EMBR|DELN-E1"
    asked = ep.handle(night, model_factory=compliant, data_dir=tmp_path)
    assert asked["state"] == "pending" and asked["gate_counts"]["interrupts"] == 1
    sent = ep.handle(day, model_factory=morning, data_dir=tmp_path)
    assert sent["state"] == "sent" and sent["composed_by"] == "model" and sent["withdrawn"] == [key]
    assert sent["gate_counts"]["interrupts"] == 0  # the paused run was released, not asked again
    assert sent["card"]["withdrawn_reason"] == SUPERSEDED_REASON and sent["card"]["answer"] is None
    assert Inbox(tmp_path / "inbox.json").pending("r9") == []
    late = ep.handle({**night, "answer": True}, model_factory=compliant, data_dir=tmp_path)
    assert late["state"] == "already_sent" and late["delivered_state"] == "sent" and late["plan"] == sent["plan"]
    # the next night poll for the same outage: still one message
    assert ep.handle(night, model_factory=compliant, data_dir=tmp_path)["state"] == "already_sent"


def test_the_morning_after_in_a_recycled_container(tmp_path):
    """The same morning, but the container that asked is gone: the card is known (the inbox file, or Memory)
    and no paused run exists, so the plan is drafted afresh; still sent, still superseded, still one question."""
    ep = load_entrypoint()
    night = {"rider_id": "r10", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True}
    one, two = tmp_path / "one", tmp_path / "two"
    asked = ep.handle(night, model_factory=compliant, data_dir=one)
    assert asked["state"] == "pending"
    (two / "sessions").mkdir(parents=True)
    (two / "inbox.json").write_text((one / "inbox.json").read_text())  # what Memory would hand the new session
    sent = ep.handle({**night, "after_dark": False}, model_factory=compliant, data_dir=two)
    assert (
        sent["state"] == "sent" and sent["composed_by"] == "model" and sent["withdrawn"] == [asked["card"]["case_key"]]
    )
    assert sent["gate_counts"]["interrupts"] == 0


def test_an_answer_never_fails(tmp_path):
    """A double tap on yes, a changed mind after a no, and an answer to a question that was never asked: each
    returns a well-formed state, never an error. The delivered plan answers the first two; the third is
    delivered under the answer (yes: sent, no: held), the model composing it, no question raised."""
    ep = load_entrypoint()

    def resumed(trip, decision):  # the resumed run continues from the tool result: the Plan comes next
        return ScriptedModel([plan_call(composed_plan(decision), "p")])

    night = {"rider_id": "r11", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True}
    assert ep.handle(night, model_factory=compliant, data_dir=tmp_path)["state"] == "pending"
    yes = ep.handle({**night, "answer": True}, model_factory=resumed, data_dir=tmp_path)
    assert yes["state"] == "sent"
    tap = ep.handle({**night, "answer": True}, model_factory=compliant, data_dir=tmp_path)
    assert tap["state"] == "already_sent" and tap["delivered_state"] == "sent" and tap["plan"] == yes["plan"]
    no_rider = {**night, "rider_id": "r12"}
    assert ep.handle(no_rider, model_factory=compliant, data_dir=tmp_path)["state"] == "pending"
    held = ep.handle({**no_rider, "answer": False}, model_factory=resumed, data_dir=tmp_path)
    assert held["state"] == "held"
    changed = ep.handle({**no_rider, "answer": True}, model_factory=compliant, data_dir=tmp_path)
    assert changed["state"] == "already_sent" and changed["delivered_state"] == "held"  # one outage, one decision
    never_asked = {**night, "rider_id": "r13"}
    direct = ep.handle({**never_asked, "answer": True}, model_factory=compliant, data_dir=tmp_path)
    assert direct["state"] == "sent" and direct["composed_by"] == "model" and direct["gate_counts"]["interrupts"] == 0
    declined = ep.handle(
        {**never_asked, "rider_id": "r14", "answer": False}, model_factory=compliant, data_dir=tmp_path
    )
    assert declined["state"] == "held" and declined["plan"]["status"] == "hold"


def test_a_decision_belongs_to_its_outage(tmp_path):
    """A no is held for the outage it answered; when the elevator comes back the answer is forgotten, so the
    next outage of the same elevator asks afresh (and a yes is not sent unasked the next time either).
    The session's copy of the answer, restored by the session manager, is dropped by the tombstone."""
    ep = load_entrypoint()
    from le_dispatch.interrupts import DecisionMemory

    def resumed(trip, decision):
        return ScriptedModel([plan_call(composed_plan(decision), "p")])

    night = {"rider_id": "r15", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True}
    key = "r15|DELN>EMBR|DELN-E1"
    assert ep.handle(night, model_factory=compliant, data_dir=tmp_path)["state"] == "pending"
    assert ep.handle({**night, "answer": False}, model_factory=resumed, data_dir=tmp_path)["state"] == "held"
    assert ep.handle(night, model_factory=compliant, data_dir=tmp_path)["state"] == "already_sent"
    back = ep.handle({**night, "outages": []}, model_factory=compliant, data_dir=tmp_path)
    assert back["state"] == "quiet" and back["forgotten"] == [key]
    memory = DecisionMemory(tmp_path / "r15-decisions.json")
    assert memory.get(key) is None and key in memory._tombstones
    again = ep.handle(night, model_factory=compliant, data_dir=tmp_path)
    assert again["state"] == "pending" and again["gate_counts"]["interrupts"] == 1  # asked afresh
    assert again["forgotten"] == []
    assert ep.handle(night, model_factory=compliant, data_dir=tmp_path)["state"] == "pending"  # not twice
    yes = ep.handle({**night, "answer": True}, model_factory=resumed, data_dir=tmp_path)
    assert yes["state"] == "sent"
    assert key not in DecisionMemory(tmp_path / "r15-decisions.json")._tombstones  # the new answer spent it
    # a yes is not carried over either: back, out again, asked again
    assert ep.handle({**night, "outages": []}, model_factory=compliant, data_dir=tmp_path)["forgotten"] == [key]
    assert ep.handle(night, model_factory=compliant, data_dir=tmp_path)["state"] == "pending"


def test_the_conversation_belongs_to_its_outage(tmp_path):
    """A sent outage leaves a session (the messages, the tool results); the quiet poll that follows deletes it,
    so the next outage of the same trip starts a clean conversation rather than continuing last month's;
    a paused question's session goes the same way (the card is withdrawn first, so a late answer is refused
    without the session). A quiet poll on a trip that never had a session leaves nothing behind."""
    import json

    ep = load_entrypoint()
    day = {"rider_id": "r16", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}
    sessions = tmp_path / "sessions"
    assert ep.handle(day, model_factory=compliant, data_dir=tmp_path)["state"] == "sent"
    session_dir = sessions / "session_le-r16-DELN-EMBR"
    assert session_dir.is_dir()
    first_messages = sum(1 for _ in session_dir.rglob("message_*.json"))
    assert first_messages >= 3
    back = ep.handle({**day, "outages": []}, model_factory=compliant, data_dir=tmp_path)
    assert back["state"] == "quiet" and back["session_reset"] is True and not session_dir.exists()
    again = ep.handle({**day, "outages": []}, model_factory=compliant, data_dir=tmp_path)
    assert again["session_reset"] is False and not session_dir.exists()  # nothing to close, nothing created
    assert ep.handle(day, model_factory=compliant, data_dir=tmp_path)["state"] == "sent"
    assert sum(1 for _ in session_dir.rglob("message_*.json")) == first_messages  # a clean conversation
    night = {**day, "rider_id": "r17", "after_dark": True}
    assert ep.handle(night, model_factory=compliant, data_dir=tmp_path)["state"] == "pending"
    assert ep.handle({**night, "outages": []}, model_factory=compliant, data_dir=tmp_path)["session_reset"] is True
    late = ep.handle({**night, "answer": True}, model_factory=compliant, data_dir=tmp_path)
    assert late["state"] == "withdrawn"  # the card, not the session, answers the late tap
    assert json.loads((tmp_path / "inbox.json").read_text())["cards"]


def test_one_outage_one_message(tmp_path):
    """Poll 1 sends; poll 2 with the same outage returns already_sent and calls no model; the elevator comes
    back (quiet) and goes out again: a new message. A held plan is remembered the same way."""
    ep = load_entrypoint()
    calls: list[str] = []

    def counting(trip, decision):
        calls.append(trip.case_key)
        return compliant(trip, decision)

    day = {"rider_id": "r8", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}
    first = ep.handle(day, model_factory=counting, data_dir=tmp_path)
    assert first["state"] == "sent" and len(calls) == 1
    second = ep.handle(day, model_factory=counting, data_dir=tmp_path)
    assert second["state"] == "already_sent" and second["plan"] == first["plan"] and second["sent_at"]
    assert second["delivered_state"] == "sent"
    assert len(calls) == 1  # no model was built or called for the repeat
    back = ep.handle({**day, "outages": []}, model_factory=counting, data_dir=tmp_path)
    assert back["state"] == "quiet"
    third = ep.handle(day, model_factory=counting, data_dir=tmp_path)
    assert third["state"] == "sent" and len(calls) == 2  # a new outage of the same elevator is a new message
    # another elevator at the same station is another case: sent on its own
    other = ep.handle({**day, "outages": ["DELN-E1", "DELN-E2"]}, model_factory=counting, data_dir=tmp_path)
    assert other["state"] in ("sent", "already_sent")


def test_invalid_payloads_never_run_anything(tmp_path):
    """A bad payload gets state invalid with a reason; no model, no file, no state change. Then a hundred
    random payloads: the entrypoint always answers with a known state and never raises."""
    import random

    ep = load_entrypoint()
    calls: list[str] = []

    def counting(trip, decision):
        calls.append(trip.case_key)
        return compliant(trip, decision)

    bad = [
        None,
        [],
        {},
        {"rider_id": "", "origin": "DELN", "destination": "EMBR"},
        {"rider_id": "r", "origin": 12, "destination": "EMBR"},
        {"rider_id": "r", "origin": "DELN", "destination": "EMBR", "outages": "DELN-E1"},
        {"rider_id": "r", "origin": "DELN", "destination": "EMBR", "outages": [1]},
        {"rider_id": "r", "origin": "DELN", "destination": "EMBR", "after_dark": "yes"},
        {"rider_id": "r", "origin": "DELN", "destination": "EMBR", "answer": "yes"},
    ]
    for payload in bad:
        out = ep.handle(payload, model_factory=counting, data_dir=tmp_path)
        assert out["state"] == "invalid" and out["reason"] and out["plan"] is None, payload
    assert calls == [] and not list(tmp_path.iterdir())

    rng = random.Random(7)
    values = [None, "", "DELN", "EMBR", "ZZZZ", "DELN-E1", 0, 1, True, False, [], ["DELN-E1"], ["x", 3], {"a": 1}]
    keys = ["rider_id", "origin", "destination", "outages", "via", "after_dark", "last_train", "answer", "extra"]
    states = set()
    for _ in range(100):
        payload = {k: rng.choice(values) for k in rng.sample(keys, rng.randint(0, len(keys)))}
        out = ep.handle(payload, model_factory=counting, data_dir=tmp_path)
        assert out["state"] in {"invalid", "quiet", "sent", "held", "pending", "withdrawn", "already_sent"}, payload
        states.add(out["state"])
    assert "invalid" in states


def test_observability_is_configured_only_when_the_runtime_provides_an_endpoint(monkeypatch):
    """A real OTLP exporter would try to reach the endpoint from every later span in this process, so the
    Strands telemetry setup is replaced by a recorder here; the branch logic is what is under test."""
    import strands.telemetry as telemetry

    calls: list[str] = []

    class Recorder:
        def setup_otlp_exporter(self):
            calls.append("otlp")

    ep = load_entrypoint()
    monkeypatch.setattr(telemetry, "StrandsTelemetry", Recorder)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert ep.setup_observability().startswith("none") and calls == []
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert ep.setup_observability() == "otlp (http://collector:4318)" and calls == ["otlp"]

    class Missing:
        def setup_otlp_exporter(self):
            raise ImportError("no exporter")

    monkeypatch.setattr(telemetry, "StrandsTelemetry", Missing)
    assert ep.setup_observability().startswith("unavailable")


def test_prompt_shaped_invocations_reach_the_same_contract(tmp_path):
    """What the evaluation runner and `agentcore invoke` send: {"prompt": ...}. The exported dataset's
    inputs start with the payload as JSON and run unchanged; a plain sentence naming the elevator runs too."""
    import json

    from le_dispatch.agentcore_eval import export_dataset, scenario_input
    from le_dispatch.interfaces import fixture_policy, load_cases

    ep = load_entrypoint()
    kb, policy = fixture_policy()
    cases = load_cases()
    dataset = export_dataset(cases[:3], kb, policy)
    for i, scenario in enumerate(dataset["scenarios"]):
        text = scenario["turns"][0]["input"]
        assert text.startswith("{") and scenario_input(cases[i], i) == text
        out = ep.handle({"prompt": text}, model_factory=compliant, data_dir=tmp_path / f"s{i}")
        assert out["state"] == "sent", scenario["scenario_id"]
        assert out["plan"]["option"] == scenario["metadata"]["expected_option"]
        assert f"with option {out['plan']['option']}" in scenario["turns"][0]["expected_response"]
        assert out["plan"]["elevator"] == scenario["metadata"]["elevator"]
    # the payload inside the text is the poller's contract, byte for byte
    first = json.loads(dataset["scenarios"][0]["turns"][0]["input"].split("} ")[0] + "}")
    assert set(first) == {"rider_id", "origin", "destination", "outages"}
    # a sentence, as a person would type it into agentcore invoke
    out = ep.handle(
        {"prompt": "Plan my trip from DELN to EMBR. Elevator DELN-E1 at DELN is out and it is after dark."},
        model_factory=compliant,
        data_dir=tmp_path / "sentence",
    )
    assert out["state"] == "pending" and out["card"]["elevator"] == "DELN-E1"
    bad = ep.handle({"prompt": "hello there"}, model_factory=compliant, data_dir=tmp_path / "bad")
    assert bad["state"] == "invalid" and "elevator" in bad["reason"]


def test_the_toolkit_facing_app_module_exposes_a_module_level_app(monkeypatch):
    """`agentcore configure -e infra/agentcore/runtime/app.py` needs a module-level app; building it does
    not start a server and does not call Bedrock (the model factory is lazy)."""
    pytest.importorskip("bedrock_agentcore")
    import importlib.util

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    spec = importlib.util.spec_from_file_location("le_app", ROOT / "infra" / "agentcore" / "runtime" / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["le_app"] = module
    spec.loader.exec_module(module)
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    assert isinstance(module.app, BedrockAgentCoreApp)
    assert module.MODEL_ID == "us.amazon.nova-lite-v1:0" and module.REGION == "us-west-2"
    from starlette.testclient import TestClient

    with TestClient(module.app) as client:
        assert client.get("/ping").status_code == 200
        out = client.post(
            "/invocations", json={"rider_id": "r", "origin": "DELN", "destination": "EMBR", "outages": []}
        )
        assert out.status_code == 200 and out.json()["state"] == "quiet"  # no model needed for a quiet trip


def test_the_app_module_serves_on_the_stand_in_without_a_key(monkeypatch, tmp_path):
    """LAST_ELEVATOR_MODEL_ID=stand-in and LAST_ELEVATOR_MEMORY_ID=stand-in: the same app module the toolkit
    points at serves the whole contract on the learner stand-in and an in-memory Memory, nothing called
    (make serve is this plus uvicorn). Driven through Starlette's in-memory client."""
    pytest.importorskip("bedrock_agentcore")
    from starlette.testclient import TestClient

    monkeypatch.setenv("LAST_ELEVATOR_MODEL_ID", "stand-in")
    monkeypatch.setenv("LAST_ELEVATOR_MEMORY_ID", "stand-in")
    monkeypatch.setenv("LAST_ELEVATOR_DATA", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "rt_app_stand_in", ROOT / "infra" / "agentcore" / "runtime" / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    day = {"rider_id": "r30", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}
    with TestClient(module.app) as client:
        assert client.get("/ping").status_code == 200
        sent = client.post("/invocations", json=day).json()
        assert sent["state"] == "sent" and sent["composed_by"] == "model" and sent["memory"]["status"] == "ok"
        assert client.post("/invocations", json=day).json()["state"] == "already_sent"
        dark = client.post("/invocations", json={**day, "rider_id": "r31", "after_dark": True}).json()
        assert dark["state"] == "pending" and dark["card"]["question"].startswith("It is after dark.")
        yes = client.post("/invocations", json={**day, "rider_id": "r31", "after_dark": True, "answer": True}).json()
        assert yes["state"] == "sent"
        spec2 = importlib.util.spec_from_file_location("serve_script", ROOT / "scripts" / "serve.py")
        serve = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(serve)
        lines = serve.curl_lines(8080)
        assert lines[0].endswith("/ping") and sum(1 for line in lines if "/invocations" in line) == len(serve.EXAMPLES)
        for what, payload in serve.EXAMPLES:  # every printed curl line is a payload the served app answers
            body = client.post("/invocations", json={**payload, "rider_id": "serve-" + payload["rider_id"]}).json()
            assert body["state"] in ("sent", "already_sent", "quiet", "pending"), (what, body)
            if "note" in payload:
                assert body["note"]["read_by"] == "model" and body["note"]["constraints"] == ["avoid_ramps"], body
