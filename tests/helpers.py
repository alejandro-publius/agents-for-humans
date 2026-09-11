"""Shared test helpers."""

from __future__ import annotations

from typing import Any


def tool_results(agent) -> list[dict[str, Any]]:
    """Every toolResult block in the agent's conversation, in order."""
    return [b["toolResult"] for m in agent.messages for b in m["content"] if "toolResult" in b]


def result_text(tool_result: dict[str, Any]) -> str:
    return " ".join(c.get("text", "") for c in tool_result.get("content", []))
