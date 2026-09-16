"""F6: dataset export in the documented schema, the custom evaluator on mock
traces, the dry-run plan, and the results writer that never overwrites."""

from __future__ import annotations

import json

import pytest
from le_dispatch.agentcore_eval import (
    DATASET_PATH,
    EVALUATORS_PATH,
    case_trip,
    credentials_present,
    dataset_stats,
    export_dataset,
    plan,
    run_apply,
    run_local_evaluation,
    scores_entry,
    write_exports,
    write_scores,
)
from le_dispatch.evaluators.option_equality import evaluate, lambda_handler
from le_dispatch.interfaces import load_cases
from le_dispatch.messages import composed_plan


def payload(spans, expected="alternate_elevator", level="TRACE"):
    return {
        "schemaVersion": "1.0",
        "evaluatorId": "custom-abc1234567",
        "evaluatorName": "LastElevatorOptionEquality",
        "evaluationLevel": level,
        "evaluationInput": {"sessionSpans": spans},
        "evaluationReferenceInputs": [{"expected_option": expected}],
        "evaluationTarget": {"traceIds": ["t1"], "spanIds": []},
    }


def tool_span(name, args):
    return {
        "name": f"execute_tool {name}",
        "attributes": {"gen_ai.tool.name": name, "gen_ai.tool.call.arguments": json.dumps(args)},
    }


def test_custom_evaluator_on_three_mock_traces():
    good = [tool_span("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": "alternate_elevator"})]
    wrong = [tool_span("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": "transit"})]
    empty = [{"name": "invoke_agent", "attributes": {"gen_ai.operation.name": "chat"}}]
    assert evaluate(payload(good)) == {
        "label": "PASS",
        "value": 1.0,
        "explanation": "agent chose 'alternate_elevator' (draft_plan:gen_ai.tool.call.arguments), "
        "matching the KB label",
    }
    fail = evaluate(payload(wrong))
    assert fail["label"] == "FAIL" and fail["value"] == 0.0 and "'transit'" in fail["explanation"]
    missing = lambda_handler(payload(empty), None)
    assert missing["label"] == "FAIL" and "no plan option" in missing["explanation"]
    # the last plan-shaped call wins, and the Plan structured-output call counts
    retried = wrong + [tool_span("Plan", {"station": "DELN", "option": "alternate_elevator", "added_minutes": 4})]
    assert evaluate(payload(retried))["label"] == "PASS"
    # ground truth may arrive as a JSON string content field
    p = payload(good)
    p["evaluationReferenceInputs"] = [{"content": json.dumps({"expected_option": "alternate_elevator"})}]
    assert evaluate(p)["label"] == "PASS"
    err = evaluate({**payload(good), "evaluationReferenceInputs": []})
    assert err["errorCode"] == "MISSING_GROUND_TRUTH"


def test_dataset_export_matches_documented_schema(fixture_stack):
    kb, policy = fixture_stack
    cases = load_cases()
    ds = export_dataset(cases, kb, policy)
    assert set(ds) == {"scenarios"} and len(ds["scenarios"]) == 194
    s = ds["scenarios"][0]
    assert set(s) == {"scenario_id", "turns", "expected_trajectory", "assertions", "metadata"}
    top = policy(case_trip(cases[0], 0)).top_option
    assert s["turns"][0]["input"] and f"with option {top}" in s["turns"][0]["expected_response"]
    assert s["metadata"]["expected_option"] == top  # what the custom evaluator compares
    assert s["expected_trajectory"] == ["draft_plan", "Plan"]
    assert s["metadata"]["expected_option"] == top and s["metadata"]["case_label"] == cases[0].label
    assert len({x["scenario_id"] for x in ds["scenarios"]}) == 194
    # ground truth is code's decision: every expected option is BART's top for that elevator
    for c, sc in zip(cases, ds["scenarios"], strict=False):
        assert sc["metadata"]["expected_option"] == policy(case_trip(c)).top_option
    stats = dataset_stats(ds)
    assert stats["scenarios"] == 194 and stats["stations"] == 50 and stats["elevators"] == 97
    assert stats["labels"] == {"alternate_elevator": 55, "backtracking": 53, "transit": 86}
    assert sum(stats["expected_options"].values()) == 194


def test_checked_in_exports_are_current(fixture_stack, tmp_path):
    kb, policy = fixture_stack
    ds, stats = write_exports(load_cases(), kb, policy, tmp_path, tmp_path / "stats.json")
    assert json.loads(DATASET_PATH.read_text()) == ds
    cfg = json.loads(EVALUATORS_PATH.read_text())
    builtin = {e["evaluator_id"]: e["level"] for e in cfg["builtin"]}
    assert builtin["Builtin.ToolSelectionAccuracy"] == "TOOL_CALL"
    assert cfg["custom"][0]["code"].endswith("option_equality.py")
    assert stats["provenance"]["claimable"] is False


def test_dry_run_plan_prints_stats_and_calls_without_network(fixture_stack):
    kb, policy = fixture_stack
    ds = export_dataset(load_cases(), kb, policy)
    p = plan(ds, agent_runtime_arn="arn:aws:bedrock-agentcore:us-west-2:0:runtime/x")
    text = p.render()
    assert "194 scenarios" in text and "nothing below has been executed" in text
    assert "Builtin.ToolSelectionAccuracy" in text and "LastElevatorOptionEquality" in text
    assert "invoke_agent_runtime" in text and "x194" in text and "create_evaluator" in text
    assert credentials_present() is False
    with pytest.raises(RuntimeError, match="no AWS credentials"):
        run_apply(p, yes=True)


def test_results_writer_never_overwrites_local_entries(tmp_path):
    path = tmp_path / "policy_agreement.json"
    path.write_text(
        json.dumps({"entries": [{"provider": "mock", "model_id": "mock-echo", "mode": "enforced", "cases": 194}]})
    )
    scores = [{"label": "PASS", "value": 1.0}] * 190 + [{"label": "FAIL", "value": 0.0}] * 4
    entry = scores_entry(scores, model_id="us.amazon.nova-lite-v1:0", mode="enforced", evaluator_id="custom/option")
    assert entry["cases"] == 194 and entry["agree"] == 190 and entry["agreement_pct"] == 97.9
    doc = write_scores(entry, path)
    assert doc["entries"][0] == {"provider": "mock", "model_id": "mock-echo", "mode": "enforced", "cases": 194}
    assert doc["entries"][1]["provider"] == "agentcore-evaluations"
    # rerun replaces the same agentcore row instead of duplicating it
    doc = write_scores({**entry, "agree": 191}, path)
    assert len(doc["entries"]) == 2 and doc["entries"][1]["agree"] == 191
    # a different mode is a new row
    doc = write_scores({**entry, "mode": "no_steering"}, path)
    assert len(doc["entries"]) == 3


def test_evaluator_reads_real_strands_spans(fixture_stack):
    """The evaluator finds the option in the spans Strands really emits (the
    gen_ai.tool.message event on the execute_tool Plan span), on every case."""
    from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call

    kb, policy = fixture_stack
    cases = load_cases()

    def compliant(case, trip):
        d = policy(trip)
        plan = composed_plan(d)
        return ScriptedModel(
            [
                tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t"),
                plan_call(plan, "p"),
            ]
        )

    doc = run_local_evaluation(cases[:12], kb, policy, model_factory=compliant)
    assert doc["scenarios"] == 12 and doc["pass"] == 12 and doc["fail"] == 0
    assert doc["provenance"]["claimable"] is False
    assert all(r["spans"] >= 5 for r in doc["results"])
    assert set(doc["option_found_in"]) == {"Plan:gen_ai.tool.message.content"}

    def wrong(case, trip):  # steering off below, so the wrong option reaches the spans and the evaluator sees it
        d = policy(trip)
        other = next(o for o in kb.option_labels if o != d.top_option)
        plan = {"station": d.station, "elevator": d.elevator, "option": other, "added_minutes": 1, "rider_message": "m"}
        return ScriptedModel(
            [
                tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": other}, "t"),
                plan_call(plan, "p"),
            ]
        )

    bad = run_local_evaluation(cases[:3], kb, policy, model_factory=wrong, steering=False)
    assert bad["pass"] == 0 and bad["fail"] == 3
    assert "KB label is" in bad["results"][0]["explanation"]
