"""E7. The tools over MCP stdio carry the same guarantees, and an agent over MCP gets demo-one's plan."""

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters, stdio_client
from strands import Agent
from strands.tools.mcp import MCPClient

from agent.mock_model import MockModel
from agent.schema import Plan
from bart import BartClient
from policy import Outage, assess
from scripts.demo_one import FRAGMENT, TRIP, WHEN

REPO_ROOT = Path(__file__).resolve().parents[1]
ELEVATOR = "PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS)"


@pytest.fixture
def mcp_client():
    env = {**os.environ, "PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}"}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.mcp_server"], env=env, cwd=str(REPO_ROOT)
    )
    client = MCPClient(lambda: stdio_client(params))
    with client:
        yield client


def _tool_results(agent):
    return [b["toolResult"] for m in agent.messages for b in m["content"] if "toolResult" in b]


def test_mcp_exposes_the_two_tools_and_refuses_unknown_stations(mcp_client, no_network):
    names = sorted(t.tool_name for t in mcp_client.list_tools_sync())
    assert names == ["get_station_facts", "plan_alternatives"]
    bad = mcp_client.call_tool_sync(
        tool_use_id="t1", name="get_station_facts", arguments={"station_abbr": "ZZZZ"}
    )
    assert json.loads(bad["content"][0]["text"])["error"].startswith("CANCELLED: station_abbr='ZZZZ'")
    bad_elev = mcp_client.call_tool_sync(
        tool_use_id="t2",
        name="plan_alternatives",
        arguments={
            "origin": "SANL",
            "destination": "EMBR",
            "outage_station": "SANL",
            "outage_elevator": "NOPE",
        },
    )
    assert "not an elevator the KB lists" in json.loads(bad_elev["content"][0]["text"])["error"]
    assert no_network.attempts == []  # stdio pipes only


def test_agent_over_mcp_gets_the_same_plan_as_demo_one(mcp_client, no_network):
    policy_top = assess(TRIP, Outage("SANL", ELEVATOR, FRAGMENT), WHEN, BartClient(api_key=None)).top_option
    model = MockModel(
        [
            {"type": "tool_use", "name": "get_station_facts", "input": {"station_abbr": "SANL"}},
            {
                "type": "tool_use",
                "name": "plan_alternatives",
                "input": {
                    "origin": "SANL",
                    "destination": "EMBR",
                    "outage_station": "SANL",
                    "outage_elevator": ELEVATOR,
                    "when_iso": WHEN.isoformat(),
                },
            },
            {
                "type": "tool_use",
                "name": "Plan",
                "input": {
                    "affected": True,
                    "option": policy_top,
                    "steps": [
                        "Take the Platform 1 elevator to the opposite platform.",
                        "Go back to Bay Fair.",
                    ],
                    "added_minutes": 14,
                    "message": "Backtrack via Bay Fair.",
                },
            },
        ]
    )
    agent = Agent(
        model=model, tools=mcp_client.list_tools_sync(), structured_output_model=Plan, callback_handler=None
    )
    result = agent("Outage SANL platform 2; trip SANL to EMBR.")

    facts, plan_payload = (json.loads(r["content"][0]["text"]) for r in _tool_results(agent)[:2])
    assert facts["abbr"] == "SANL" and facts["source_url"].endswith("/stations/SANL/accessible")
    assert plan_payload["top_option"] == policy_top == "backtracking"
    assert plan_payload["ranked_options"][0]["added_minutes"] == 14  # computed by the server's policy engine
    assert isinstance(result.structured_output, Plan)
    assert result.structured_output.option == policy_top  # same option make demo-one prints
    assert no_network.attempts == []
