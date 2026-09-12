"""Last Elevator MCP server over stdio: get_station_facts and plan_alternatives with the same
guarantees as the in-process tools.

    python -m src.mcp_server            # speaks MCP on stdin/stdout (mcp 2.x MCPServer, formerly FastMCP)

The KB check that the BeforeToolCall hook performs in-process is performed inside each tool here,
so an MCP caller cannot name a station or elevator the KB does not know; plan_alternatives is the
policy engine, so options, minutes, and flags are computed by code, never by the caller.
"""

from __future__ import annotations

import json
import sys

from mcp.server.mcpserver import MCPServer

from agent.hooks import kb_elevator_validator, kb_station_validator
from agent.tools import get_station_facts as _facts
from agent.tools import plan_alternatives as _plan

server = MCPServer(name="last-elevator", instructions="BART elevator outage facts and policy-ranked options.")
_station_ok = kb_station_validator("station_abbr")
_plan_ok = kb_station_validator("origin", "destination", "outage_station")
_elev_ok = kb_elevator_validator("outage_station", "outage_elevator")


@server.tool(name="get_station_facts")
def get_station_facts(station_abbr: str) -> str:
    """Look up one BART station's elevators and BART's documented outage options (knowledge base only)."""
    reason = _station_ok({"station_abbr": station_abbr})
    if reason:
        return json.dumps({"error": f"CANCELLED: {reason}"})
    return _facts(station_abbr=station_abbr)


@server.tool(name="plan_alternatives")
def plan_alternatives(
    origin: str, destination: str, outage_station: str, outage_elevator: str, when_iso: str | None = None
) -> str:
    """Run the policy engine: affected?, condition, BART's documented option, ranked feasible options with
    computed minutes, after-dark and last-train flags. Code decides all of it."""
    args = {
        "origin": origin,
        "destination": destination,
        "outage_station": outage_station,
        "outage_elevator": outage_elevator,
    }
    reason = _plan_ok(args) or _elev_ok(args)
    if reason:
        return json.dumps({"error": f"CANCELLED: {reason}"})
    return _plan(origin=origin, destination=destination, outage_station=outage_station,
                 outage_elevator=outage_elevator, when_iso=when_iso)  # fmt: skip


if __name__ == "__main__":
    server.run(transport="stdio")
    sys.exit(0)
