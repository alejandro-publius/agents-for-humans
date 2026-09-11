"""Offline mock model provider for the Strands agent loop.

Plays back scripted turns from ``fixtures/model/*.json`` so every test and eval runs with no
credentials, no network, and $0 spend. The real agent loop (tool execution, hooks, interventions,
structured output) still runs; only the model is scripted.

Fixture format::

    {
      "name": "one_turn_text",
      "description": "what this script exercises",
      "turns": [
        {"type": "text", "text": "Plain assistant reply; ends the turn."},
        {"type": "tool_use", "name": "get_station_facts", "input": {"station": "DELN"}},
        {"type": "tool_use", "name": "Plan", "input": {...}}      # structured output: the tool is
                                                                    # named after the Pydantic class
      ]
    }

Each ``stream()`` call consumes exactly one turn. Running out of turns raises ``MockExhausted``
so a mis-scripted test fails loudly instead of looping.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any

from strands.models.model import Model

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "model"

_USAGE = {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}, "metrics": {"latencyMs": 0}}


class MockExhausted(RuntimeError):
    """The agent asked the mock model for more turns than the fixture scripted."""


class FixtureError(ValueError):
    """A fixture file is malformed."""


def _validate_turn(turn: dict[str, Any], index: int, fixture: str) -> dict[str, Any]:
    kind = turn.get("type")
    if kind == "text":
        if not isinstance(turn.get("text"), str):
            raise FixtureError(f"{fixture}: turn {index} type=text needs a string 'text'")
    elif kind == "tool_use":
        if not isinstance(turn.get("name"), str) or not isinstance(turn.get("input"), dict):
            raise FixtureError(f"{fixture}: turn {index} type=tool_use needs 'name' (str) and 'input' (dict)")
    else:
        raise FixtureError(f"{fixture}: turn {index} has unknown type {kind!r} (expected text|tool_use)")
    return turn


def load_fixture(name_or_path: str | Path) -> dict[str, Any]:
    """Load and validate a fixture by bare name (``one_turn_text``) or path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = FIXTURE_DIR / f"{path.name}.json"
    if not path.exists():
        raise FixtureError(f"model fixture not found: {path}")
    data = json.loads(path.read_text())
    if not isinstance(data.get("turns"), list) or not data["turns"]:
        raise FixtureError(f"{path.name}: 'turns' must be a non-empty list")
    data["turns"] = [_validate_turn(t, i, path.name) for i, t in enumerate(data["turns"])]
    data.setdefault("name", path.stem)
    return data


def text_events(text: str) -> list[dict[str, Any]]:
    """Bedrock-style stream events for a plain text turn."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": text}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": _USAGE},
    ]


def tool_use_events(name: str, tool_input: dict[str, Any], tool_use_id: str) -> list[dict[str, Any]]:
    """Bedrock-style stream events for a single tool call."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tool_use_id, "name": name}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": _USAGE},
    ]


class MockModel(Model):
    """Scripted stand-in for a real model provider. Never opens a socket."""

    def __init__(self, turns: list[dict[str, Any]], *, name: str = "mock") -> None:
        self.name = name
        self._turns = [_validate_turn(dict(t), i, name) for i, t in enumerate(turns)]
        self._cursor = 0
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def from_fixture(cls, name_or_path: str | Path) -> MockModel:
        data = load_fixture(name_or_path)
        return cls(data["turns"], name=data["name"])

    # --- introspection for tests and evals -------------------------------------------------
    @property
    def turns_remaining(self) -> int:
        return len(self._turns) - self._cursor

    @property
    def turns_consumed(self) -> int:
        return self._cursor

    def _next_turn(self) -> dict[str, Any]:
        if self._cursor >= len(self._turns):
            raise MockExhausted(
                f"mock model {self.name!r} exhausted after {self._cursor} turn(s); "
                "the agent loop asked for another model call. Script more turns or fix the loop."
            )
        turn = self._turns[self._cursor]
        self._cursor += 1
        return turn

    # --- strands Model interface -----------------------------------------------------------
    def update_config(self, **model_config: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {"model_id": f"mock:{self.name}", "provider": "mock", "cost_usd": 0.0}

    async def stream(
        self,
        messages: list[Any],
        tool_specs: list[Any] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[dict[str, Any]]:
        last_user_text = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                blocks = message.get("content", [])
                last_user_text = " ".join(b.get("text", "") for b in blocks if "text" in b)
                break
        self.calls.append(
            {
                "tool_names": [spec["name"] for spec in (tool_specs or [])],
                "system_prompt": system_prompt,
                "last_user_text": last_user_text,
                "tool_choice": kwargs.get("tool_choice"),
            }
        )
        turn = self._next_turn()
        if turn["type"] == "text":
            events = text_events(turn["text"])
        else:
            events = tool_use_events(turn["name"], turn["input"], f"mock-{self._cursor}")
        for event in events:
            yield event

    async def structured_output(self, output_model: Any, prompt: Any, system_prompt: Any = None, **kw: Any):
        """Legacy ``agent.structured_output()`` path: the next scripted turn must call the schema tool."""
        turn = self._next_turn()
        if turn["type"] != "tool_use" or turn["name"] != output_model.__name__:
            raise FixtureError(
                f"mock model {self.name!r}: structured_output for {output_model.__name__} needs a "
                f"tool_use turn with that name; got {turn}"
            )
        yield {"output": output_model.model_validate(turn["input"])}
