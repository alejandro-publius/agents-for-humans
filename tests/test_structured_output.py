"""A3. Every run ends with a Plan that validates against the schema."""

from agent.core import build_agent
from agent.mock_model import MockModel
from agent.schema import OPTION_ORDER, Plan
from tests.helpers import result_text, tool_results


def test_plan_tool_call_becomes_structured_output():
    model = MockModel.from_fixture("structured_plan")
    built = build_agent(model)

    result = built("Outage: EMBR: Street - Platform. Trip EMBR to ASHB.")

    plan = result.structured_output
    print("\nSTRUCTURED PLAN ->", plan)
    assert isinstance(plan, Plan)
    assert plan.affected is True
    assert plan.option == "alternate elevator" and plan.option in OPTION_ORDER
    assert plan.added_minutes == 3
    assert model.calls[0]["tool_names"][-1] == "Plan", "the Plan tool is offered to the model"


def test_loop_forces_a_plan_when_the_model_ends_with_prose():
    model = MockModel.from_fixture("structured_forced")
    built = build_agent(model)

    result = built("Outage: DELN: Platform - Richmond. Trip DELN to EMBR.")

    assert model.turns_consumed == 2
    forced_call = model.calls[1]
    assert forced_call["last_user_text"] == "You must format the previous response as structured output."
    assert forced_call["tool_choice"] == {"any": {}}
    assert forced_call["tool_names"] == ["Plan"]
    assert isinstance(result.structured_output, Plan)
    assert result.structured_output.option == "backtracking"


def test_invalid_plan_is_rejected_by_schema_then_corrected():
    model = MockModel.from_fixture("structured_invalid_then_valid")
    built = build_agent(model)

    result = built("Outage: ASHB: Street - Platform. Trip ASHB to MONT.")

    rejected = tool_results(built.agent)[0]
    assert rejected["status"] == "error"
    assert "message" in result_text(rejected)  # pydantic names the missing field
    assert isinstance(result.structured_output, Plan)
    assert result.structured_output.added_minutes == 25
