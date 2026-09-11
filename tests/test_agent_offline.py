"""Runs the real Strands agent loop against a scripted model: no credentials, no network."""

from afh_agent.agent import AGENT_NAME, SYSTEM_PROMPT, build_agent
from afh_agent.tools import days_until
from tests.fake_model import ScriptedModel, text_turn, tool_turn


def _tool_results(agent):
    """Yield every toolResult block the agent recorded in its conversation."""
    for message in agent.messages:
        for block in message.get("content", []):
            if "toolResult" in block:
                yield block["toolResult"]


def test_agent_calls_domain_tool_and_reports():
    model = ScriptedModel(
        [
            tool_turn("days_until", {"date_iso": "2026-09-14", "today_iso": "2026-09-10"}),
            text_turn("The deadline is in 4 days. Nothing needs you yet."),
        ]
    )
    agent = build_agent(model=model, tools=[days_until])

    result = agent("How long until the hackathon deadline?")

    assert "4 days" in str(result)
    assert model.calls[0]["system_prompt"] == SYSTEM_PROMPT
    assert model.calls[0]["tool_names"] == ["days_until"]

    results = list(_tool_results(agent))
    assert len(results) == 1, "the tool call should have produced exactly one tool result"
    assert results[0]["status"] == "success"
    assert results[0]["content"] == [{"text": "4"}]


def test_agent_metadata():
    agent = build_agent(model=ScriptedModel([]), tools=[])
    assert agent.name == AGENT_NAME
    assert agent.system_prompt == SYSTEM_PROMPT
