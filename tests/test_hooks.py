"""A3. The BeforeToolCall hook cancels any call whose arguments fail a validator."""

from agent.core import AgentConfig, build_agent
from agent.mock_model import MockModel
from tests.helpers import result_text, tool_results


def test_hook_cancels_call_with_unknown_station():
    model = MockModel.from_fixture("hook_bad_station")
    built = build_agent(model)

    built("Outage: ZZZZ: Platform - Nowhere. Trip DELN to EMBR.")

    first = tool_results(built.agent)[0]
    print("\nHOOK CANCELLED ->", first)
    assert first["status"] == "error"
    assert "CANCELLED by ArgumentValidatorHook" in result_text(first)
    assert "station='ZZZZ' is not a known station" in result_text(first)
    (cancelled,) = built.validator_hook.cancelled
    assert cancelled == {
        "tool": "get_station_facts",
        "input": {"station": "ZZZZ"},
        "reason": "station='ZZZZ' is not a known station",
    }
    assert built.validator_hook.allowed == []


def test_hook_lets_known_station_through():
    model = MockModel.from_fixture("hook_good_station")
    built = build_agent(model)

    built("Outage: DELN: Platform - Richmond. Trip DELN to EMBR.")

    first = tool_results(built.agent)[0]
    assert first["status"] == "success"
    assert "PLACEHOLDER" in result_text(first)
    assert built.validator_hook.allowed == ["get_station_facts"]
    assert built.validator_hook.cancelled == []


def test_ablation_removes_the_hook_so_the_bad_call_runs():
    """Same bad script, hook disabled: the placeholder tool executes with the bogus station."""
    model = MockModel.from_fixture("hook_bad_station")
    built = build_agent(model, config=AgentConfig.ablated())

    built("Outage: ZZZZ: Platform - Nowhere.")

    first = tool_results(built.agent)[0]
    assert built.validator_hook is None
    assert first["status"] == "success"
    assert "ZZZZ" in result_text(first)
