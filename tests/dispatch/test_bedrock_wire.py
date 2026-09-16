"""The live path through Strands' real Bedrock adapter, offline: what is sent, whether every retry is
sendable, what an error costs. The boto3 client is a stand-in; nothing reaches the network."""

from __future__ import annotations

import importlib.util
import json

import pytest
from le_dispatch.bedrock_wire import (
    ALTERNATION_MESSAGE,
    DEAD_ENDPOINT,
    TOOL_CONFIG_MESSAGE,
    TOOL_RESULT_TURN_MESSAGE,
    UNANSWERED_MESSAGE,
    access_denied_steps,
    compliant_steps,
    converse_rule_violation,
    quick_retries,
    retries_steps,
    run_all,
    run_wire,
    throttled_steps,
    truncated_steps,
)
from le_dispatch.budget import SEPARATOR_TEXT, sendable_turns, separate_tool_result_turns
from le_dispatch.gates import SYSTEM_PROMPT, build_agent, deliver, trip_prompt
from le_dispatch.interfaces import ROOT, Trip
from le_dispatch.messages import composed_plan
from le_dispatch.plan import Plan
from strands.models.bedrock import _TOOL_RESULT_TURN_VALIDATION_MESSAGE

LIVE_MODELS = ROOT / "evals" / "live_models.json"
TRIP = Trip(rider_id="rider-wire", origin="DELN", destination="EMBR", outages=("DELN-E1",))


def _u(*texts):
    return {"role": "user", "content": [{"text": t} for t in texts]}


def _a(text="ok"):
    return {"role": "assistant", "content": [{"text": text}]}


def _tu(tool_use_id="t1"):
    block = {"toolUse": {"toolUseId": tool_use_id, "name": "draft_plan", "input": {}}}
    return {"role": "assistant", "content": [block]}


def _tr(tool_use_id="t1"):
    return {"role": "user", "content": [{"toolResult": {"toolUseId": tool_use_id, "content": [{"text": "r"}]}}]}


def test_the_request_bedrock_receives_carries_the_system_prompt_both_tools_and_the_prompt(fixture_stack):
    kb, policy = fixture_stack
    run = run_wire("compliant", compliant_steps(policy(TRIP)), kb, policy, TRIP)
    request = run.requests[0]
    assert request["modelId"] == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert request["system"] == [{"text": SYSTEM_PROMPT}]
    assert request["messages"] == [{"role": "user", "content": [{"text": trip_prompt(TRIP, policy(TRIP))}]}]
    assert "Elevator DELN-E1 at DELN is out" in request["messages"][0]["content"][0]["text"]
    tools = {t["toolSpec"]["name"]: t["toolSpec"] for t in request["toolConfig"]["tools"]}
    assert set(tools) == {"draft_plan", "Plan"}
    assert request["toolConfig"]["toolChoice"] == {"auto": {}}
    assert tools["draft_plan"]["inputSchema"]["json"]["required"] == ["station", "elevator", "option"]
    plan_schema = tools["Plan"]["inputSchema"]["json"]
    assert set(Plan.model_fields) <= set(plan_schema["properties"])
    assert "approved_messages" in plan_schema["properties"]["rider_message"]["description"]
    assert "guardrailConfig" not in request  # no guardrail is configured; the gates are in-process
    assert run.outcome.composed_by == "model" and run.summary()["rejected_by_converse_rules"] == 0


def test_the_second_request_carries_the_tool_result_with_the_approved_sentences(fixture_stack):
    kb, policy = fixture_stack
    d = policy(TRIP)
    run = run_wire("compliant", compliant_steps(d), kb, policy, TRIP)
    assert len(run.requests) == 2
    roles = [m["role"] for m in run.requests[1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    tool_use = run.requests[1]["messages"][1]["content"][0]["toolUse"]
    assert tool_use["name"] == "draft_plan" and tool_use["input"]["station"] == d.station
    tool_result = run.requests[1]["messages"][2]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == tool_use["toolUseId"]
    assert composed_plan(d)["rider_message"] in json.dumps(tool_result)
    assert run.outcome.plan == composed_plan(d)


def test_every_retry_is_accepted_at_the_first_attempt(fixture_stack):
    kb, policy = fixture_stack
    run = run_wire("retries", retries_steps(policy(TRIP), kb), kb, policy, TRIP)
    s = run.summary()
    assert (s["hook_cancels"], s["guide_before_tool"], s["guide_after_model"]) == (1, 1, 2)
    assert s["rejected_by_converse_rules"] == 0 and s["requests"] == s["model_calls"] == 6
    assert all(converse_rule_violation(r) is None for r in run.requests)
    assert run.outcome.composed_by == "model" and run.outcome.plan == composed_plan(policy(TRIP))
    # the separator the SDK would have inserted after a rejection is already there, once, after the tool result
    last = run.requests[-1]["messages"]
    separators = [m for m in last if m["role"] == "assistant" and m["content"] == [{"text": SEPARATOR_TEXT}]]
    assert len(separators) == 1
    assert run.bundle.agent.messages != last  # request-local: the persisted conversation is untouched


def test_without_the_passes_the_second_guide_is_unsendable(fixture_stack):
    kb, policy = fixture_stack
    steps = retries_steps(policy(TRIP), kb)
    fold_only = run_wire("fold_only", steps, kb, policy, TRIP, mode="fold_only")
    assert fold_only.summary()["rejected_by_converse_rules"] == 1  # the SDK's lazy separator: one rejected request
    assert fold_only.outcome.composed_by == "model"
    rejected = [e for e in fold_only.fake.exchanges if not e.accepted]
    assert rejected[0].detail == TOOL_RESULT_TURN_MESSAGE
    none = run_wire("none", steps, kb, policy, TRIP, mode="none")
    assert none.summary()["rejected_by_converse_rules"] == 2
    assert none.outcome.composed_by == "code" and none.outcome.stop_reason == "exception"
    assert "ValidationException" in none.outcome.reason and ALTERNATION_MESSAGE in none.outcome.reason
    assert none.outcome.plan == composed_plan(policy(TRIP))  # the rider still got the plan


def test_a_permission_error_costs_one_call_and_the_rider_still_gets_the_plan(fixture_stack):
    kb, policy = fixture_stack
    run = run_wire("denied", access_denied_steps(), kb, policy, TRIP)
    s = run.summary()
    assert s["model_calls"] == 1 and s["requests"] == 1
    assert run.outcome.composed_by == "code" and "AccessDeniedException" in run.outcome.reason
    assert run.outcome.plan == composed_plan(policy(TRIP))


def test_a_throttle_is_retried_by_the_sdk_and_counts_against_the_cap(fixture_stack):
    kb, policy = fixture_stack
    run = run_wire("throttled", throttled_steps(policy(TRIP)), kb, policy, TRIP, retry_strategy=quick_retries())
    s = run.summary()
    assert run.outcome.composed_by == "model" and s["model_calls"] == 3 and s["requests"] == 3
    assert run.fake.exchanges[0].reply == "ThrottlingException"
    assert run.outcome.usage["model_calls"] == 3


def test_a_truncated_response_costs_one_call_and_the_rider_still_gets_the_plan(fixture_stack):
    kb, policy = fixture_stack
    run = run_wire("truncated", truncated_steps(policy(TRIP)), kb, policy, TRIP)
    s = run.summary()
    assert s["model_calls"] == 1 and run.fake.exchanges[0].reply == "tool_use draft_plan"
    assert run.outcome.composed_by == "code" and "MaxTokensReachedException" in run.outcome.reason
    assert run.outcome.plan == composed_plan(policy(TRIP))


@pytest.mark.parametrize("model_id", [m["model_id"] for m in json.loads(LIVE_MODELS.read_text())["models"]])
def test_both_live_model_ids_go_through_the_adapter_and_the_tool_result_carries_the_sentences(fixture_stack, model_id):
    kb, policy = fixture_stack
    d = policy(TRIP)
    run = run_wire("compliant", compliant_steps(d), kb, policy, TRIP, model_id=model_id)
    assert run.outcome.composed_by == "model" and run.summary()["rejected_by_converse_rules"] == 0
    assert run.requests[0]["modelId"] == model_id
    tool_result = run.requests[1]["messages"][2]["content"][0]["toolResult"]
    assert composed_plan(d)["rider_message"] in json.dumps(tool_result)  # JSON for Anthropic, text for Nova


def test_the_stand_in_enforces_the_rules_the_sdk_relies_on():
    assert TOOL_RESULT_TURN_MESSAGE == _TOOL_RESULT_TURN_VALIDATION_MESSAGE  # the SDK's separator keys on it
    ok = {"messages": [_u("hi"), _tu(), _tr(), _a(SEPARATOR_TEXT), _u("guide")], "toolConfig": {"tools": []}}
    assert converse_rule_violation(ok) is None
    assert converse_rule_violation({"messages": [_u("a"), _u("b")]}) == ALTERNATION_MESSAGE
    assert converse_rule_violation({"messages": [_a("x")]}) == ALTERNATION_MESSAGE
    assert converse_rule_violation({"messages": [_u("hi"), _tu(), _tr(), _u("g")], "toolConfig": {}}) == (
        TOOL_RESULT_TURN_MESSAGE
    )
    assert converse_rule_violation({"messages": [_u("hi"), _tu(), _u("no result")], "toolConfig": {}}) == (
        UNANSWERED_MESSAGE
    )
    assert converse_rule_violation({"messages": [_u("hi"), _tu(), _tr()]}) == TOOL_CONFIG_MESSAGE


def test_the_separator_pass_matches_the_sdk_and_is_idempotent():
    from strands.models.bedrock import BedrockModel

    conversation = [_u("hi"), _tu(), _tr(), _u("g1"), _u("g2"), _tu("t2"), _tr("t2")]
    ours = sendable_turns(conversation)
    theirs = BedrockModel._separate_tool_result_turns([_u("hi"), _tu(), _tr(), _u("g1", "g2"), _tu("t2"), _tr("t2")])
    assert ours == theirs
    assert separate_tool_result_turns(ours) == ours
    assert conversation[3] == _u("g1")  # not mutated
    assert converse_rule_violation({"messages": ours, "toolConfig": {}}) is None


def test_the_real_client_is_pointed_at_a_closed_local_port_before_it_is_replaced():
    from strands.models.bedrock import BedrockModel

    model = BedrockModel(model_id="us.amazon.nova-lite-v1:0", region_name="us-west-2", endpoint_url=DEAD_ENDPOINT)
    assert model.client.meta.endpoint_url == DEAD_ENDPOINT


def test_all_scenarios_and_the_script_write_stable_files(fixture_stack, tmp_path):
    kb, policy = fixture_stack
    runs = run_all(kb, policy, TRIP)
    assert {n: r.outcome.composed_by for n, r in runs.items()} == {
        "compliant": "model",
        "retries": "model",
        "retries_fold_only": "model",
        "retries_no_passes": "code",
        "access_denied": "code",
        "throttled": "model",
        "truncated": "code",
        "hung": "code",
        "prose_then_forced": "model",
        "human_moment_yes": "model",
        "human_moment_no": "model",
    }
    assert runs["hung"].summary()["requests"] == 1 and "ReadTimeoutError" in runs["hung"].outcome.reason
    spec = importlib.util.spec_from_file_location("bedrock_wire_script", ROOT / "scripts" / "bedrock_wire.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    out, results = tmp_path / "evidence", tmp_path / "bedrock_wire.json"
    argv = ["--out", str(out), "--results", str(results)]
    assert script.main(argv) == 0
    first = {p.name: p.read_bytes() for p in out.iterdir()} | {"results": results.read_bytes()}
    assert script.main(argv) == 0
    second = {p.name: p.read_bytes() for p in out.iterdir()} | {"results": results.read_bytes()}
    assert first == second
    request = json.loads((out / "bedrock-request.json").read_text())
    assert request["modelId"] and "toolConfig" in request
    doc = json.loads(results.read_text())
    assert doc["scenarios"]["retries"]["rejected_by_converse_rules"] == 0
    assert doc["provenance"]["claimable"] is False  # fixtures; the laptop reruns on the exports
    in_repo = json.loads((ROOT / "results" / "bedrock_wire.json").read_text())
    assert in_repo["scenarios"] == doc["scenarios"]


@pytest.mark.parametrize("mode", ["both", "fold_only", "none", "bogus"])
def test_sendability_modes_are_named(mode, fixture_stack):
    kb, policy = fixture_stack
    if mode == "bogus":
        with pytest.raises(ValueError):
            run_wire("x", compliant_steps(policy(TRIP)), kb, policy, TRIP, mode=mode)
    else:
        run = run_wire("x", compliant_steps(policy(TRIP)), kb, policy, TRIP, mode=mode)
        assert run.summary()["sendability"] == mode


def _load_script(name):
    spec = importlib.util.spec_from_file_location(f"{name}_script", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_learner_stand_in_serves_a_whole_live_eval_entry(fixture_stack):
    """One client for every case: the belief resets on a fresh conversation, the plan is the model's on every
    case, no request rejected, the enforced mode costs the guide the first guess earns."""
    from le_dispatch.bedrock_wire import wired_learner_model
    from le_dispatch.eval_live import LiveModel, run_entry
    from le_dispatch.interfaces import load_cases

    kb, policy = fixture_stack
    cases = load_cases()[:12]
    model = wired_learner_model("us.amazon.nova-lite-v1:0")
    entry = run_entry(
        LiveModel("nova", "stand-in", "us.amazon.nova-lite-v1:0"),
        "enforced",
        cases,
        kb,
        policy,
        model_factory=lambda m: model,
        cap=200,
    )
    assert (entry["cases"], entry["agree"], entry["composed_by_code"]) == (12, 12, 0)
    assert model.client.cases == 12 and model.client.rejected == 0
    assert 24 <= entry["calls_used"] <= 36  # two calls per case, three when the first guess is not the top option
    assert entry["claimable"] is False


def test_eval_live_stand_in_is_the_live_path_without_the_network(capsys, tmp_path):
    script = _load_script("eval_live")
    out = tmp_path / "stand-in.json"
    assert script.main(["--stand-in", "--limit-cases", "5", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "nothing called" in printed and "plumbing proof only" in printed
    doc = json.loads(out.read_text())
    assert len(doc["entries"]) == 4
    assert {e["provider"] for e in doc["entries"]} == {"stand-in"}
    assert all(e["cases"] == 5 and e["agree"] == 5 and not e["claimable"] for e in doc["entries"])
    assert not (ROOT / "results" / "le-eval-live-stand-in.json").exists()


def test_demo_live_stand_in_writes_a_packet_composed_by_the_model(capsys, tmp_path):
    script = _load_script("demo_live")
    assert script.main(["--stand-in", "--out", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "nothing called" in printed and "composed_by=model" in printed
    packets = list(tmp_path.glob("stand-in-*.json"))
    assert len(packets) == 1
    packet = json.loads(packets[0].read_text())
    assert packet["delivery"]["composed_by"] == "model" and "nothing called" in packet["provenance"]["run"]
    assert packet["provenance"]["claimable"] is False
    assert not list((ROOT / "docs" / "evidence").glob("stand-in-*"))


@pytest.mark.parametrize("answer", [True, False], ids=["yes", "no"])
def test_the_human_moment_on_the_wire_asks_once_and_every_request_is_accepted(fixture_stack, tmp_path, answer):
    """The learner's first call is wrong; after dark the run pauses on it; on the resumed pass the gates
    retry it; one answer ends the run, and every request the real adapter built was accepted."""
    from le_dispatch import tracing
    from le_dispatch.bedrock_wire import wired_learner_model
    from le_dispatch.interrupts import DecisionMemory, Inbox, build_decision_run

    kb, policy = fixture_stack
    trip = Trip("rider-wire", "DELN", "EMBR", ("DELN-E1",), after_dark=True)
    model = wired_learner_model("us.amazon.nova-lite-v1:0")
    run = build_decision_run(
        model, kb, policy, trip, inbox=Inbox(tmp_path / "inbox.json"), memory=DecisionMemory(tmp_path / "m.json")
    )
    assert run.start().state == "pending"
    out = run.resume(answer)
    assert out.state == ("sent" if answer else "held") and out.composed_by == "model"
    assert out.plan is not None and out.plan.option == policy(trip).top_option
    assert run.handler.count(tracing.INTERRUPT_RAISED) == 1
    assert model.client.rejected == 0 and all(converse_rule_violation(r) is None for r in model.client.requests)
    assert 3 <= len(model.client.requests) <= 8


def test_the_hook_names_the_affected_station_and_elevator_and_the_learner_recovers_from_it_alone(fixture_stack):
    """A bare prompt (no station, no elevator): the learner's first call names nothing the KB knows; the
    hook's cancel message names the right values, and the learner reaches the plan on them."""
    from le_dispatch.bedrock_wire import wired_learner_model

    kb, policy = fixture_stack
    model = wired_learner_model("us.amazon.nova-lite-v1:0")
    bundle = build_agent(model, kb, policy, TRIP)
    out = deliver(bundle, "Plan my trip.")
    assert out.composed_by == "model" and out.plan == composed_plan(policy(TRIP))
    cancels = [e for e in bundle.hook.events if e.kind == "hook.cancel_tool"]
    assert cancels and "the affected station is 'DELN' and the elevator that is out is 'DELN-E1'" in cancels[0].reason
    assert any("took the station and elevator it named" in r for r in model.client.learner.repairs)
    assert model.client.rejected == 0


def test_the_runtime_state_machine_on_the_wire_across_invocations(fixture_stack, tmp_path):
    """Every state of the runtime entrypoint with a model that reads the conversation, through the real
    adapter, one fresh model per invocation (as on the runtime), the file session carrying the pause: sent,
    already_sent, quiet, pending, pending again (not asked twice), the answer resumes in a new invocation,
    held on no; every request accepted."""
    import importlib.util

    from le_dispatch.bedrock_wire import wired_learner_model

    spec = importlib.util.spec_from_file_location(
        "entrypoint_wire", ROOT / "infra" / "agentcore" / "runtime" / "entrypoint.py"
    )
    ep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ep)
    kb, policy = fixture_stack
    clients = []

    def factory(trip, decision):
        model = wired_learner_model("us.amazon.nova-lite-v1:0")
        clients.append(model.client)
        return model

    common = dict(model_factory=factory, kb=kb, policy=policy, data_dir=tmp_path)
    base = {"rider_id": "r9", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}
    assert ep.handle(base, **common)["state"] == "sent"
    assert ep.handle(base, **common)["state"] == "already_sent"
    assert ep.handle({**base, "outages": []}, **common)["state"] == "quiet"
    dark = {**base, "rider_id": "r10", "after_dark": True}
    assert ep.handle(dark, **common)["state"] == "pending"
    assert ep.handle(dark, **common)["state"] == "pending"  # the next poll: not asked again
    answered = ep.handle({**dark, "answer": True}, **common)
    assert answered["state"] == "sent" and answered["plan"]["option"] == policy(ep.trip_from(dark)).top_option
    assert ep.handle(dark, **common)["state"] == "already_sent"
    dark2 = {**base, "rider_id": "r11", "after_dark": True}
    assert ep.handle(dark2, **common)["state"] == "pending"
    declined = ep.handle({**dark2, "answer": False}, **common)
    assert declined["state"] == "held" and declined["plan"]["status"] == "hold"
    assert ep.handle(dark2, **common)["delivered_state"] == "held"
    assert sum(c.rejected for c in clients) == 0
    assert all(converse_rule_violation(r) is None for c in clients for r in c.requests)


def test_every_persona_converges_through_the_adapter_in_both_tool_result_formats(fixture_stack):
    """The offline convergence study, through the real adapter: Anthropic model ids get JSON tool results
    with a status flag, Nova gets text without one; every persona must read the feedback either way."""
    from le_dispatch.bedrock_wire import run_wire_convergence
    from le_dispatch.interfaces import load_cases

    kb, policy = fixture_stack
    ids = tuple(m["model_id"] for m in json.loads(LIVE_MODELS.read_text())["models"])
    doc = run_wire_convergence(kb, policy, load_cases()[:3], ids)
    assert doc["runs"] == 3 * 9 * len(ids) and doc["converged"] == doc["runs"], doc["per_model"]
    assert doc["rejected_by_converse_rules"] == 0 and 2 <= doc["max_calls"] <= 6
    in_repo = json.loads((ROOT / "results" / "wire_convergence.json").read_text())
    assert in_repo["runs"] == in_repo["converged"] == 432 and in_repo["provenance"]["claimable"] is False


def test_an_off_slice_wire_convergence_run_lands_beside_the_pinned_file(tmp_path, monkeypatch, capsys):
    """`make wire-convergence WIRE_CASES=194` on the laptop must not overwrite the 24-case slice the claims
    pin: any other case count writes results/wire_convergence_<N>.json unless --out says where."""
    script = _load_script("wire_convergence")
    monkeypatch.setattr(script, "RESULTS", tmp_path / "wire_convergence.json")
    assert script.main(["--cases", "2"]) == 0
    printed = capsys.readouterr().out
    assert (tmp_path / "wire_convergence_2.json").exists() and not (tmp_path / "wire_convergence.json").exists()
    assert "wrote" in printed and "wire_convergence_2.json" in printed
    assert script.main(["--cases", "2", "--out", str(tmp_path / "named.json")]) == 0
    assert (tmp_path / "named.json").exists()
