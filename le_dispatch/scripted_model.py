"""Offline scripted Model for strands-agents 1.55.1.

A script is a list of steps; each step is the exact stream a model call
returns. Verified event order for a tool call (section 3, fact 4 of the work
order) and for a text turn. No network, no credentials, deterministic.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable
from typing import Any

from strands.models.model import Model

_USAGE = {"usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, "metrics": {"latencyMs": 1}}


def tool_call(name: str, args: dict[str, Any], tool_use_id: str) -> list[dict[str, Any]]:
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tool_use_id, "name": name}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": _USAGE},
    ]


def text_turn(text: str) -> list[dict[str, Any]]:
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {}}},
        {"contentBlockDelta": {"delta": {"text": text}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": _USAGE},
    ]


def plan_call(plan: dict[str, Any], tool_use_id: str, model_name: str = "Plan") -> list[dict[str, Any]]:
    """A structured-output tool call; Strands names the tool after the Pydantic class."""
    return tool_call(model_name, plan, tool_use_id)


class ScriptedModel(Model):
    """Replays scripted steps. When the script runs out it ends the turn with a
    marker text so a runaway loop fails loudly instead of hanging."""

    def __init__(self, steps: list[list[dict[str, Any]]], name: str = "scripted"):
        self.steps = list(steps)
        self.calls = 0
        self.name = name

    def update_config(self, **kwargs: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {"model_id": self.name, "offline": True}

    def structured_output(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - not used
        raise NotImplementedError("scripted model uses the structured output tool path")

    async def stream(  # type: ignore[override]  # the SDK signature carries keyword-only options this replay ignores
        self, messages: Any, tool_specs: Any = None, system_prompt: Any = None, **kwargs: Any
    ) -> AsyncIterable[dict[str, Any]]:
        idx = self.calls
        self.calls += 1
        step = self.steps[idx] if idx < len(self.steps) else text_turn("[script exhausted]")
        for event in step:
            yield event
