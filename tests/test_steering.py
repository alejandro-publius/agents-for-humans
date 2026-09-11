"""A3. The steering handler rewrites a response when the option-order policy check fails."""

from agent.core import AgentConfig, build_agent
from agent.mock_model import MockModel
from agent.steering import first_option_mentioned

TEXT_ONLY = dict(structured_output=False)  # end the run on the text turn so the rewrite is the final answer


def test_steering_rewrites_response_that_recommends_a_lower_option():
    model = MockModel.from_fixture("steering_bad_order")
    built = build_agent(model, config=AgentConfig(required_option="backtracking", **TEXT_ONLY))

    result = built("Outage: DELN: Platform - Richmond. Trip DELN to EMBR.")
    final = str(result).strip()
    print("\nSTEERING REWROTE ->", built.steering.rewrites[0])

    assert first_option_mentioned(built.steering.rewrites[0]["original"]) == "mitigation_shuttle"
    assert first_option_mentioned(final) == "backtracking"
    assert final.startswith("Backtracking is the first feasible option under BART's published outage order.")
    assert "response recommends 'mitigation_shuttle'" in final
    # The rewrite is also what the conversation history keeps, not just what the caller sees.
    assert built.agent.messages[-1]["content"][0]["text"] == final
    assert built.steering.passed == 0


def test_steering_leaves_compliant_response_alone():
    model = MockModel.from_fixture("steering_good_order")
    built = build_agent(model, config=AgentConfig(required_option="backtracking", **TEXT_ONLY))

    result = built("Outage: DELN: Platform - Richmond. Trip DELN to EMBR.")

    assert str(result).startswith("Use backtracking: ride one stop past Del Norte")
    assert built.steering.rewrites == []
    assert built.steering.passed == 1


def test_ablation_removes_steering_so_the_bad_response_stands():
    model = MockModel.from_fixture("steering_bad_order")
    built = build_agent(model, config=AgentConfig.ablated(required_option="backtracking", **TEXT_ONLY))

    result = built("Outage: DELN: Platform - Richmond. Trip DELN to EMBR.")

    assert built.steering is None
    assert first_option_mentioned(str(result)) == "mitigation_shuttle"


def test_policy_with_no_required_option_never_rewrites():
    model = MockModel.from_fixture("steering_bad_order")
    built = build_agent(model, config=AgentConfig(required_option=None, **TEXT_ONLY))

    result = built("anything")

    assert first_option_mentioned(str(result)) == "mitigation_shuttle"
    assert built.steering.rewrites == []
