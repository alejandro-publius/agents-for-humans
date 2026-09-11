"""A scripted stand-in for a real model so the agent loop can run offline in tests and CI.

Each "turn" is the list of stream events a Bedrock-style model would emit for one assistant
message. Build turns with text_turn() and tool_turn(); ScriptedModel plays them back in order.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable
from typing import Any

from strands.models.model import Model

_USAGE = {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}, "metrics": {"latencyMs": 0}}


def text_turn(text: str) -> list[dict[str, Any]]:
    """Assistant replies with plain text and ends its turn."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": text}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": _USAGE},
    ]


def tool_turn(name: str, tool_input: dict[str, Any], tool_use_id: str = "tooluse_1") -> list[dict[str, Any]]:
    """Assistant asks to call `name` with `tool_input`."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tool_use_id, "name": name}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": _USAGE},
    ]


class ScriptedModel(Model):
    """Plays back scripted turns and records every request the agent loop makes."""

    def __init__(self, turns: list[list[dict[str, Any]]]):
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    # --- Model interface -------------------------------------------------------------------
    def update_config(self, **model_config: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {"model_id": "scripted"}

    async def stream(
        self,
        messages: list[Any],
        tool_specs: list[Any] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[dict[str, Any]]:
        self.calls.append(
            {
                "messages": messages,
                "tool_names": [spec["name"] for spec in (tool_specs or [])],
                "system_prompt": system_prompt,
            }
        )
        if not self._turns:
            raise RuntimeError("ScriptedModel exhausted: the agent asked for more turns than scripted")
        for event in self._turns.pop(0):
            yield event

    async def structured_output(
        self, output_model: Any, prompt: Any, system_prompt: Any = None, **kwargs: Any
    ):
        raise NotImplementedError("ScriptedModel does not support structured output")
        yield  # pragma: no cover - makes this an async generator
