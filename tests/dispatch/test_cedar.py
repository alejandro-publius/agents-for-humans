"""F5: generated Cedar covers the KB, denies fakes locally, and the plan makes no calls."""

from __future__ import annotations

import json

import pytest
from le_dispatch.agentcore_policy import IAM_PERMISSIONS, apply, credentials_present, plan
from le_dispatch.cedar_gen import (
    POLICY_DIR,
    SCHEMA_FILE,
    generate,
    load_tools,
    local_decision,
    request,
    schema_for,
    validate_locally,
    write_policies,
)
from le_dispatch.interfaces import BART_OPTION_ORDER

ARN = "arn:aws:bedrock-agentcore:us-west-2:000000000000:gateway/last-elevator"


@pytest.fixture
def generated(fixture_stack):
    kb, _ = fixture_stack
    target, tools = load_tools()
    return kb, target, tools, generate(kb, target, tools, ARN)


def test_cedar_contains_every_station_and_label(generated):
    kb, target, tools, files = generated
    permit = files["permit_kb_tools.cedar"]
    assert len(kb.stations) == 50 and len(kb.option_labels) == 5
    for code in kb.stations:
        assert f'"{code}"' in permit
    for label in BART_OPTION_ORDER:
        assert f'"{label}"' in permit
    for tool in tools:
        assert f'AgentCore::Action::"{target}___{tool.name}"' in permit
    assert files["forbid_unknown_station.cedar"].count("forbid(") == sum(len(t.station_params) for t in tools)
    assert files["forbid_unknown_option.cedar"].count("forbid(") == sum(len(t.option_params) for t in tools)
    # BART's order is preserved verbatim in the option set
    ordered = ", ".join(f'"{o}"' for o in BART_OPTION_ORDER)
    assert ordered in permit


def test_generation_is_deterministic(generated, tmp_path):
    kb, target, tools, files = generated
    again = generate(kb, target, tools, ARN)
    assert files == again
    manifest = write_policies(files, kb, target, tools, tmp_path)
    assert manifest["stations"] == 50 and manifest["elevators"] == 97
    assert (tmp_path / "manifest.json").exists() and (tmp_path / "permit_kb_tools.cedar").exists()
    assert json.loads((tmp_path / "manifest.json").read_text())["validation_mode"] == "FAIL_ON_ANY_FINDINGS"


def test_checked_in_policies_match_the_fixture_kb(generated):
    kb, target, tools, _ = generated
    manifest = json.loads((POLICY_DIR / "manifest.json").read_text())
    assert manifest["stations"] == len(kb.stations) and manifest["tools"] == [t.name for t in tools]
    files = generate(kb, target, tools)  # placeholder ARN, as checked in
    for name, text in files.items():
        assert (POLICY_DIR / name).read_text() == text


def test_local_cedar_evaluation_denies_fake_station_and_option(generated):
    kb, target, tools, files = generated
    policies = "\n".join(files.values())
    station = sorted(kb.stations)[0]
    elevator = sorted(e for e in kb.elevators if e.startswith(station))[0]
    ok = request(target, "draft_plan", ARN, station=station, elevator=elevator, option="backtracking")
    fake_station = request(target, "draft_plan", ARN, station="ZZZZ", elevator=elevator, option="backtracking")
    fake_option = request(target, "draft_plan", ARN, station=station, elevator=elevator, option="teleport")
    fake_elevator = request(target, "draft_plan", ARN, station=station, elevator="ZZZZ-E9", option="backtracking")
    missing_station = request(target, "draft_plan", ARN, elevator=elevator, option="backtracking")
    decisions = [local_decision(policies, r) for r in (ok, fake_station, fake_option, fake_elevator, missing_station)]
    if decisions[0] is None:
        pytest.skip("cedarpy not installed: structural checks above stand in for local evaluation")
    assert decisions == ["Allow", "Deny", "Deny", "Deny", "Deny"]
    # a second governed tool with two station params
    both = request(target, "affected_trips", ARN, origin=station, destination=sorted(kb.stations)[1])
    one_fake = request(target, "affected_trips", ARN, origin=station, destination="NOPE")
    assert local_decision(policies, both) == "Allow" and local_decision(policies, one_fake) == "Deny"
    # an ungoverned tool has no permit: default deny
    assert local_decision(policies, request(target, "unknown_tool", ARN, station=station)) == "Deny"


def test_dry_run_plan_lists_resources_and_permissions_without_calls():
    p = plan(mcp_endpoint="https://example.invalid/mcp")
    ops = [s.operation.split(".")[-1] for s in p.steps]
    assert ops[0] == "create_policy_engine" and ops[-1] == "create_gateway_target"
    assert ops.count("create_policy") == 4 and "create_gateway" in ops
    rendered = p.render()
    assert "nothing below has been executed" in rendered
    assert "FAIL_ON_ANY_FINDINGS" in rendered and "ENFORCE" in rendered and "https://example.invalid/mcp" in rendered
    assert all(perm in rendered for perm in IAM_PERMISSIONS)
    existing = plan(gateway_id="gw-123")
    assert any(s.operation.endswith("update_gateway") for s in existing.steps)


def test_apply_refuses_without_credentials_or_yes():
    assert credentials_present() is False  # the conftest strips every key
    with pytest.raises(RuntimeError, match="no AWS credentials"):
        apply(plan(), yes=True)


def test_generated_policies_validate_against_the_schema(generated):
    """The same check AgentCore runs at create_policy with FAIL_ON_ANY_FINDINGS."""
    kb, target, tools, files = generated
    schema = schema_for(target, tools)
    assert set(schema["AgentCore"]["actions"]) == {f"{target}___{t.name}" for t in tools}
    passed, errors = validate_locally("\n".join(files.values()), schema)
    if passed is None:
        pytest.skip("cedarpy not installed")
    assert passed is True and errors == []
    # a typo in a context attribute is a finding, so it would be rejected at creation time
    broken = files["permit_kb_tools.cedar"].replace("context.input.station", "context.input.statoin", 1)
    passed_broken, _ = validate_locally(broken, schema)
    assert passed_broken is False
    # an action the gateway does not expose is a finding too
    unknown = files["permit_kb_tools.cedar"].replace(f"{target}___draft_plan", f"{target}___teleport", 1)
    assert validate_locally(unknown, schema)[0] is False


def test_checked_in_schema_and_manifest_are_current(generated):
    kb, target, tools, _ = generated
    assert json.loads((POLICY_DIR / SCHEMA_FILE).read_text()) == schema_for(target, tools)
    manifest = json.loads((POLICY_DIR / "manifest.json").read_text())
    assert manifest["schema"] == SCHEMA_FILE and manifest["local_validation"] in ("passed", "cedarpy not installed")


def test_cedar_and_python_hook_agree_on_random_inputs(generated):
    """Two enforcement layers, one rule: for random station, elevator and
    option values (KB codes and fakes), the gateway's Cedar decision equals
    what the in-process KB hook plus the label check would allow."""
    import random

    from le_dispatch.gates import KBHook

    kb, target, tools, files = generated
    policies = "\n".join(files.values())
    if (
        local_decision(
            policies, request(target, "draft_plan", ARN, station="DELN", elevator="DELN-E1", option="transit")
        )
        is None
    ):
        pytest.skip("cedarpy not installed")
    rng = random.Random(7)
    stations = sorted(kb.stations) + ["ZZZZ", "FAKE", "12TX"]
    elevators = sorted(kb.elevators) + ["ZZZZ-E1", "DELN-E9", "12TH-E2"]
    options = list(kb.option_labels) + ["walk", "taxi", "Transit"]
    hook = KBHook(kb)
    agreements = 0
    for _ in range(400):
        st, ev, op = rng.choice(stations), rng.choice(elevators), rng.choice(options)
        cedar = local_decision(policies, request(target, "draft_plan", ARN, station=st, elevator=ev, option=op))

        class _Event:  # the slice of BeforeToolCallEvent the hook reads
            tool_use = {"name": "draft_plan", "input": {"station": st, "elevator": ev, "option": op}}
            cancel_tool = False

        event = _Event()
        hook.check(event)
        python_allows = not event.cancel_tool and kb.has_label(op)
        assert (cedar == "Allow") == python_allows, (st, ev, op, cedar, event.cancel_tool)
        agreements += 1
    assert agreements == 400
