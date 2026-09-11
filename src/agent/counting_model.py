"""Wrap a real model provider so every call is counted and a hard budget is enforced.

``CountingModel.calls`` mirrors ``MockModel.calls`` (one dict per stream call), so everything that
reports ``len(model.calls)`` works for live providers too. Exceeding the budget raises
``BudgetExhausted`` before any request is sent.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass, field
from typing import Any

from strands.models.model import Model


class BudgetExhausted(RuntimeError):
    """The shared model-call budget is spent; no further requests will be made."""


@dataclass
class CallBudget:
    cap: int
    used: int = 0
    exhausted_at: str | None = field(default=None)

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.cap


class CountingModel(Model):
    def __init__(self, inner: Model, budget: CallBudget, *, name: str = "counted") -> None:
        self.inner = inner
        self.budget = budget
        self.name = name
        self.calls: list[dict[str, Any]] = []

    def update_config(self, **model_config: Any) -> None:
        self.inner.update_config(**model_config)

    def get_config(self) -> Any:
        return self.inner.get_config()

    def _charge(self, tool_specs: list[Any] | None) -> None:
        if self.budget.exhausted:
            raise BudgetExhausted(f"model-call budget of {self.budget.cap} spent")
        self.budget.used += 1
        self.calls.append({"n": self.budget.used, "tool_names": [t["name"] for t in (tool_specs or [])]})

    async def stream(
        self,
        messages: list[Any],
        tool_specs: list[Any] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[Any]:
        self._charge(tool_specs)
        async for event in self.inner.stream(messages, tool_specs, system_prompt, **kwargs):
            yield event

    async def structured_output(self, output_model: Any, prompt: Any, system_prompt: Any = None, **kw: Any):
        self._charge(None)
        async for event in self.inner.structured_output(output_model, prompt, system_prompt, **kw):
            yield event
