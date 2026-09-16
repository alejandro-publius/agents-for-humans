"""F18: the same harness, a different agency, zero code changes.

A synthetic agency with other station codes, a different published option
order and other minutes goes through every stage: policy ranking in the
agency's order, the gates and the red team, Cedar generation and local
evaluation, the evaluation dataset, the approved messages, convergence."""

from __future__ import annotations

import json

import pytest
from le_dispatch.adaptive import run_convergence
from le_dispatch.agentcore_eval import dataset_stats, export_dataset
from le_dispatch.cedar_gen import GovernedTool, generate, local_decision, request, schema_for, validate_locally
from le_dispatch.gates import build_agent, deliver
from le_dispatch.interfaces import Trip
from le_dispatch.messages import approved_messages, composed_plan, is_approved
from le_dispatch.portability import kb_json, synthetic_agency
from le_dispatch.red_team import run_red_team_exhaustive, write_results
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call


@pytest.fixture(scope="module")
def agency():
    return synthetic_agency()


def test_policy_ranks_in_the_agencys_own_order(agency):
    kb, cases, policy = agency
    assert kb.option_labels[0] == "backtracking"  # not BART's order
    for c in cases[:6]:
        d = policy(Trip("r", c.station, "ZZZ9" if c.station != "ZZZ9" else "ATN0", (c.elevator,)))
        labels = [o.label for o in d.ranked]
        assert labels == sorted(labels, key=kb.rank) and d.top_option == labels[0]


def test_gates_and_messages_work_unchanged(agency):
    kb, cases, policy = agency
    c = cases[0]
    trip = Trip("r", c.station, "BTN1", (c.elevator,))
    d = policy(trip)
    wrong = next(o for o in kb.option_labels if o != d.top_option)
    good = composed_plan(d)
    del good["status"]
    model = ScriptedModel(
        [
            tool_call(
                "draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t1"
            ),  # BART code: foreign here
            tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": wrong}, "t2"),
            tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t3"),
            plan_call({**good, "rider_message": "my own words"}, "p1"),
            plan_call(good, "p2"),
        ]
    )
    bundle = build_agent(model, kb, policy, trip)
    out = deliver(bundle)
    assert out.composed_by == "model" and out.plan["option"] == d.top_option
    assert bundle.hook.cancels == 1 and is_approved(out.plan["rider_message"], d)
    assert any("second lift" in m or "far platform" in m for m in approved_messages(d))  # the agency's own words


def test_exhaustive_red_team_on_the_other_agency(agency, tmp_path):
    kb, cases, policy = agency
    result = run_red_team_exhaustive(kb, policy, cases[:12])
    doc = write_results(result, tmp_path / "rt.json", provenance="portability test")
    assert doc["runs"] == 12 * 14 and all(v == 0 for v in doc["reached_rider"].values())
    assert doc["plans_delivered"] == doc["runs"] and doc["composed_by_code"] == 12


def test_cedar_and_dataset_generate_from_the_other_kb(agency, tmp_path):
    kb, cases, policy = agency
    tools = [GovernedTool("draft_plan", ["station"], ["elevator"], ["option"])]
    files = generate(kb, "agency-b-mcp", tools, "arn:aws:bedrock-agentcore:us-west-2:0:gateway/b")
    policies = "\n".join(files.values())
    st = sorted(kb.stations)[0]
    ok = request(
        "agency-b-mcp",
        "draft_plan",
        "arn:aws:bedrock-agentcore:us-west-2:0:gateway/b",
        station=st,
        elevator=f"{st}-E1",
        option="transit",
    )
    bart = request(
        "agency-b-mcp",
        "draft_plan",
        "arn:aws:bedrock-agentcore:us-west-2:0:gateway/b",
        station="DELN",
        elevator="DELN-E1",
        option="transit",
    )
    if local_decision(policies, ok) is not None:
        assert local_decision(policies, ok) == "Allow" and local_decision(policies, bart) == "Deny"
        assert validate_locally(policies, schema_for("agency-b-mcp", tools))[0] is True
    ds = export_dataset(cases, kb, policy)
    stats = dataset_stats(ds)
    assert stats["scenarios"] == len(cases) and stats["stations"] == 12
    assert json.dumps(kb_json(kb))  # the documented JSON shape round-trips


def test_convergence_on_the_other_agency(agency):
    kb, cases, policy = agency
    doc = run_convergence(kb, policy, cases[:4])
    assert doc["converged"] == doc["runs"] == 4 * 9 and doc["max_calls"] <= 5


def test_the_synthetic_agency_runs_through_the_real_adapter_with_the_learner():
    """Other codes, another published order, station names: the learner stand-in reads the conversation and
    reaches every plan through the real Bedrock adapter, no request rejected (portability on the wire)."""
    from le_dispatch.bedrock_wire import wired_learner_model
    from le_dispatch.gates import build_agent, deliver
    from le_dispatch.messages import composed_plan
    from le_dispatch.portability import synthetic_agency

    kb2, cases2, policy2 = synthetic_agency()
    for c in cases2[:12]:
        trip = Trip("r", c.station, "BTN1" if c.station != "BTN1" else "ATN0", (c.elevator,))
        model = wired_learner_model("us.amazon.nova-lite-v1:0")
        out = deliver(build_agent(model, kb2, policy2, trip))
        assert out.composed_by == "model" and out.plan == composed_plan(policy2(trip)), (c, out.reason)
        assert model.client.rejected == 0 and model.client.consumed <= 3
