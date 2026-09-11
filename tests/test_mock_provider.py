"""A2. The Strands agent loop completes on the mock provider with zero network calls."""

import socket

import pytest
from strands import Agent

from agent.mock_model import FIXTURE_DIR, FixtureError, MockExhausted, MockModel, load_fixture


def test_network_guard_is_armed(no_network):
    """Self-check: the fixture really refuses connections, so a zero-attempt assertion means something."""
    with pytest.raises(ConnectionError, match="network disabled"):
        socket.create_connection(("example.com", 80), timeout=1)
    assert no_network.attempts == ["socket.create_connection"]


def test_agent_completes_one_turn_with_zero_network_calls(no_network):
    model = MockModel.from_fixture("one_turn_text")
    agent = Agent(model=model, tools=[], callback_handler=None)

    result = agent("Is anyone there?")

    assert "no network" in str(result)
    assert result.stop_reason == "end_turn"
    assert model.turns_consumed == 1 and model.turns_remaining == 0
    assert model.calls[0]["last_user_text"] == "Is anyone there?"
    assert no_network.attempts == [], f"the agent tried to reach the network: {no_network.attempts}"
    assert model.get_config()["cost_usd"] == 0.0


def test_agent_tool_call_round_trip_offline(no_network):
    from strands import tool

    @tool
    def echo(word: str) -> str:
        """Return the word unchanged."""
        return word

    model = MockModel(
        [
            {"type": "tool_use", "name": "echo", "input": {"word": "elevator"}},
            {"type": "text", "text": "The tool said elevator."},
        ]
    )
    agent = Agent(model=model, tools=[echo], callback_handler=None)

    result = agent("Echo something.")

    assert "elevator" in str(result)
    assert model.calls[0]["tool_names"] == ["echo"]
    tool_results = [b["toolResult"] for m in agent.messages for b in m["content"] if "toolResult" in b]
    assert tool_results == [{"toolUseId": "mock-1", "status": "success", "content": [{"text": "elevator"}]}]
    assert no_network.attempts == []


def test_exhausted_script_fails_loudly():
    model = MockModel([{"type": "text", "text": "only one"}])
    agent = Agent(model=model, tools=[], callback_handler=None)
    agent("first")
    with pytest.raises(MockExhausted):
        agent("second")


def test_every_fixture_file_is_valid():
    files = sorted(FIXTURE_DIR.glob("*.json"))
    assert files, "no fixtures in fixtures/model"
    for path in files:
        data = load_fixture(path)
        assert data["turns"]


@pytest.mark.parametrize(
    "turns",
    [
        [],
        [{"type": "text"}],
        [{"type": "tool_use", "name": "x"}],
        [{"type": "mystery"}],
    ],
)
def test_malformed_scripts_are_rejected(turns):
    with pytest.raises(FixtureError):
        MockModel(turns) if turns else load_fixture(FIXTURE_DIR / "definitely_missing")
