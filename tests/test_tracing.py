"""E5. Strands spans are exported to a file and the two guardrail spans are visible."""

import json

from agent.mock_model import MockModel
from agent.run import run_one
from agent.tracing import setup_file_tracing
from policy import Trip
from scripts.render_trace import render
from tests.test_strands_mechanics import FRAGMENT, WHEN


def test_demo_run_trace_contains_hook_cancel_and_guide_spans(tmp_path, no_network):
    trace_path = tmp_path / "trace.jsonl"
    setup_file_tracing(trace_path)  # the global tracer provider is set once for this test process

    run_one(Trip("SANL", "EMBR"), FRAGMENT, WHEN, MockModel.from_fixture("demo_one"))

    spans = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    assert any(s["name"].startswith("invoke_agent") for s in spans)
    tool_spans = [s for s in spans if s["name"].startswith("execute_tool")]
    cancelled = [s for s in tool_spans if s["attributes"].get("gen_ai.tool.name") == "get_station_facts"
                 and s["status"]["status_code"] == "ERROR"]  # fmt: skip
    guided = [s for s in tool_spans if s["attributes"].get("gen_ai.tool.name") == "draft_message"
              and s["status"]["status_code"] == "ERROR"]  # fmt: skip
    assert len(cancelled) == 1 and len(guided) == 1
    assert [e["name"] for e in cancelled[0]["events"] if e["name"].startswith("hook.")] == [
        "hook.cancel_tool"
    ]
    assert [e["name"] for e in guided[0]["events"] if e["name"].startswith("steering.")] == ["steering.guide"]

    text = render(spans)
    assert "hook.cancel_tool(" in text and "steering.guide(" in text
    assert "CANCELLED by ArgumentValidatorHook" in text
    assert no_network.attempts == []
