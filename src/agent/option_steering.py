"""Tool-level steering: the drafted option must be the policy engine's first feasible option.

Built on ``strands.vended_plugins.steering`` (verified in the installed SDK): ``steer_before_tool``
returns ``Proceed`` or ``Guide``; ``Guide`` cancels the tool call and feeds the reason back to the
model, which then retries. Attached with ``Agent(plugins=[handler])``.
"""

from __future__ import annotations

from typing import Any

from strands.vended_plugins.steering.core.action import Guide, Proceed
from strands.vended_plugins.steering.core.handler import SteeringHandler

from agent.schema import normalize_option

STEERED_TOOL = "draft_message"


class OptionOrderSteering(SteeringHandler):
    """Guides draft_message toward ``required_option`` (code's top feasible option)."""

    def __init__(self, required_option: str | None) -> None:
        super().__init__()
        self.required_option = normalize_option(required_option)
        self.guides: list[dict[str, Any]] = []
        self.proceeds: int = 0

    async def steer_before_tool(self, *, agent: Any, tool_use: dict[str, Any], **kwargs: Any):
        if tool_use.get("name") != STEERED_TOOL or self.required_option is None:
            return Proceed(reason="not the drafting tool")
        proposed = normalize_option(str((tool_use.get("input") or {}).get("option", "")))
        if proposed == self.required_option:
            self.proceeds += 1
            return Proceed(reason="option is BART's first feasible option")
        self.guides.append({"proposed": proposed, "required": self.required_option})
        return Guide(
            reason=(
                f"'{proposed}' is not BART's first feasible option for this outage; "
                f"call draft_message again with option='{self.required_option}'."
            )
        )
