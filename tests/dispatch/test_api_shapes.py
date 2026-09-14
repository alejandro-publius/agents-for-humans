"""Every AWS call the apply paths make, validated against the AWS service model botocore ships, offline: a
misnamed or missing parameter fails here instead of on the first --apply."""

from __future__ import annotations

import json

import pytest
from le_dispatch.agentcore_eval import export_dataset, reference_inputs
from le_dispatch.agentcore_eval import plan as eval_plan
from le_dispatch.agentcore_policy import api_calls as policy_api_calls
from le_dispatch.agentcore_policy import plan as policy_plan
from le_dispatch.agentcore_policy import update_gateway_params
from le_dispatch.api_shapes import check_calls, fill_placeholders, service_models_available, validate_call
from le_dispatch.evaluators.option_equality import evaluate
from le_dispatch.interfaces import load_cases, runtime_session_id

pytestmark = pytest.mark.skipif(not service_models_available(), reason="botocore without the AgentCore models")


def test_the_policy_plan_is_well_formed_for_a_new_and_for_an_existing_gateway():
    new = policy_plan(gateway_role_arn="arn:aws:iam::123456789012:role/gw", mcp_endpoint="https://example.com/mcp")
    assert check_calls(policy_api_calls(new)) == []
    existing = policy_plan(gateway_id="gateway-abcdef1234", mcp_endpoint="https://example.com/mcp")
    assert check_calls(policy_api_calls(existing)) == []
    operations = [op for _, op, _ in policy_api_calls(existing)]
    assert operations[:1] == ["create_policy_engine"] and "get_gateway" in operations and "update_gateway" in operations
    assert operations.index("get_gateway") < operations.index("update_gateway")


def test_update_gateway_without_the_required_members_is_rejected_which_is_what_the_old_plan_sent():
    bare = {"gatewayIdentifier": "gateway-abcdef1234", "policyEngineConfiguration": {"mode": "ENFORCE", "arn": "<x>"}}
    message = validate_call("bedrock-agentcore-control", "update_gateway", bare)
    assert message and "Missing required parameter" in message
    existing = {
        "gatewayId": "gateway-abcdef1234",
        "name": "last-elevator-gateway",
        "roleArn": "arn:aws:iam::123456789012:role/gw",
        "authorizerType": "AWS_IAM",
        "protocolType": "MCP",
        "description": "",
        "status": "READY",
    }
    params = update_gateway_params("gateway-abcdef1234", existing, {"mode": "ENFORCE", "arn": "<engine>"})
    assert validate_call("bedrock-agentcore-control", "update_gateway", params) is None
    assert "status" not in params and "description" not in params  # only the settings the update takes


def test_the_evaluation_calls_are_well_formed_and_the_session_id_is_long_enough(fixture_stack):
    kb, policy = fixture_stack
    dataset = export_dataset(load_cases(), kb, policy)
    p = eval_plan(dataset)
    assert check_calls(p.api_calls) == []
    invoke = next(params for _, op, params in p.api_calls if op == "invoke_agent_runtime")
    assert len(invoke["runtimeSessionId"]) >= 33
    assert json.loads(invoke["payload"].decode())["prompt"].startswith("{")


def test_a_wrong_parameter_name_is_caught():
    assert validate_call("bedrock-agentcore-control", "create_policy_engine", {"policyEngineName": "x"})
    assert validate_call(
        "bedrock-agentcore",
        "invoke_agent_runtime",
        {"agentRuntimeArn": "arn:x", "payload": b"{}", "runtimeSessionId": "short"},
    )
    assert validate_call("bedrock-agentcore-control", "no_such_operation", {}) == (
        "bedrock-agentcore-control has no operation NoSuchOperation"
    )
    assert fill_placeholders({"roleArn": "${ROLE}", "n": 1, "items": ["<id>"]}) == {
        "roleArn": "arn:aws:iam::123456789012:role/sample-role",
        "n": 1,
        "items": ["sampleid0123456789"],
    }


def test_runtime_session_ids_are_stable_and_at_least_33_characters():
    a, b = runtime_session_id("rider-1"), runtime_session_id("rider-1")
    assert a == b and len(a) >= 33 and a.startswith("le-rider-1-")
    assert runtime_session_id("rider-2") != a
    assert len(runtime_session_id("")) >= 33 and len(runtime_session_id("x" * 200)) < 100


def test_the_custom_evaluator_reads_the_ground_truth_in_the_api_shape(fixture_stack):
    kb, policy = fixture_stack
    scenario = export_dataset(load_cases()[:1], kb, policy)["scenarios"][0]
    expected = scenario["metadata"]["expected_option"]
    refs = reference_inputs(scenario, runtime_session_id("eval", scenario["scenario_id"]))
    assert (
        validate_call(
            "bedrock-agentcore",
            "evaluate",
            {
                "evaluatorId": "x" * 12,
                "evaluationInput": {"sessionSpans": [{"name": "s"}]},
                "evaluationReferenceInputs": refs,
            },
        )
        is None
    )
    plan_json = json.dumps(
        {"station": scenario["metadata"]["station"], "elevator": scenario["metadata"]["elevator"], "option": expected}
    )
    span = {
        "name": "execute_tool Plan",
        "attributes": {"gen_ai.tool.name": "Plan"},
        "events": [{"name": "gen_ai.tool.message", "attributes": {"content": plan_json}}],
    }
    verdict = evaluate({"evaluationInput": {"sessionSpans": [span]}, "evaluationReferenceInputs": refs})
    assert verdict["label"] == "PASS" and verdict["value"] == 1.0
    only_assertions = [{"assertions": [{"text": a} for a in scenario["assertions"]]}]
    assert (
        evaluate({"evaluationInput": {"sessionSpans": [span]}, "evaluationReferenceInputs": only_assertions})["label"]
        == "PASS"
    )
    wrong = json.loads(plan_json)
    wrong["option"] = "transit" if expected != "transit" else "backtracking"
    span_wrong = {**span, "events": [{"name": "gen_ai.tool.message", "attributes": {"content": json.dumps(wrong)}}]}
    assert (
        evaluate({"evaluationInput": {"sessionSpans": [span_wrong]}, "evaluationReferenceInputs": refs})["label"]
        == "FAIL"
    )


def test_the_evaluator_reads_otlp_style_spans_and_reports_missing_ground_truth():
    """The spans AgentCore hands the Lambda may carry attributes as OTLP key/value lists (value wrapped in
    a typed object) and the tool arguments as a message content list; the evaluator reads both, and says
    what is missing when the reference input carries no option."""
    otlp_span = {
        "name": "execute_tool Plan",
        "attributes": [{"key": "gen_ai.tool.name", "value": {"stringValue": "Plan"}}],
        "events": [
            {
                "name": "gen_ai.tool.message",
                "attributes": [
                    {
                        "key": "content",
                        "value": {
                            "stringValue": json.dumps(
                                [{"toolUse": {"name": "Plan", "input": {"station": "DELN", "option": "transit"}}}]
                            )
                        },
                    }
                ],
            }
        ],
    }
    refs = [{"expectedResponse": {"text": "A plan with option transit and 20 added minutes."}}]
    verdict = evaluate({"evaluationInput": {"sessionSpans": [otlp_span]}, "evaluationReferenceInputs": refs})
    assert verdict["label"] == "PASS" and "Plan:gen_ai.tool.message.content" in verdict["explanation"]
    # the final structured output on the invoke_agent span's gen_ai.choice event counts too
    choice_span = {
        "name": "invoke_agent last-elevator",
        "attributes": {},
        "events": [{"name": "gen_ai.choice", "attributes": {"message": json.dumps({"option": "backtracking"})}}],
    }
    verdict = evaluate({"evaluationInput": {"sessionSpans": [choice_span]}, "evaluationReferenceInputs": refs})
    assert verdict["label"] == "FAIL" and "invoke_agent:gen_ai.choice.message" in verdict["explanation"]
    missing = evaluate({"evaluationInput": {"sessionSpans": [otlp_span]}, "evaluationReferenceInputs": []})
    assert missing["errorCode"] == "MISSING_GROUND_TRUTH"
    nothing = evaluate({"evaluationInput": {"sessionSpans": []}, "evaluationReferenceInputs": refs})
    assert nothing["label"] == "FAIL" and "no plan option" in nothing["explanation"]
