"""Tool-level steering: the drafted option must be the policy engine's first feasible option, and
a draft that needs a rider decision (after dark, last train) pauses the run with a real Interrupt.

Built on ``strands.vended_plugins.steering`` (verified in the installed SDK 1.55.1):
``steer_before_tool`` returns ``Proceed``, ``Guide`` (cancel with feedback; the model retries) or
``Interrupt`` (the handler calls ``event.interrupt`` and the run stops with ``stop_reason ==
"interrupt"``; a truthy response on resume lets the tool run, a falsy one cancels it as denied).
Attached with ``Agent(plugins=[handler])``.

Answers are remembered per case key in ``agent.state["decisions"]`` (persisted by the session
manager) and mirrored into the ``decisions`` dict the caller passes, so an identical case does
not interrupt again: an accepted case proceeds silently, a declined case is steered to
mitigation_trip silently.
"""

from __future__ import annotations

import json
from typing import Any

from strands.vended_plugins.steering.core.action import Guide, Interrupt, Proceed
from strands.vended_plugins.steering.core.handler import SteeringHandler

from agent.schema import normalize_option

STEERED_TOOL = "draft_message"
STATE_KEY = "decisions"


class OptionOrderSteering(SteeringHandler):
    """Guides draft_message toward ``required_option``; interrupts when the case needs a rider decision."""

    def __init__(
        self,
        required_option: str | None,
        *,
        case_key: str | None = None,
        decision_flags: list[str] | None = None,
        card: dict[str, Any] | None = None,
        decisions: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.required_option = normalize_option(required_option)
        self.case_key = case_key
        self.decision_flags = list(decision_flags or [])
        self.card = card or {}
        self.decisions = decisions if decisions is not None else {}
        self.guides: list[dict[str, Any]] = []
        self.interrupts: list[dict[str, Any]] = []
        self.proceeds: int = 0

    # --- remembered answers ------------------------------------------------------------------
    def stored_answer(self, agent: Any) -> str | None:
        if not self.case_key:
            return None
        state = agent.state.get(STATE_KEY) or {}
        return state.get(self.case_key) or self.decisions.get(self.case_key)

    def remember(self, agent: Any, answer: str) -> None:
        if not self.case_key:
            return
        state = dict(agent.state.get(STATE_KEY) or {})
        state[self.case_key] = answer
        agent.state.set(STATE_KEY, state)
        self.decisions[self.case_key] = answer
        if answer == "decline":
            self.required_option = "mitigation_trip"

    # --- steering ------------------------------------------------------------------------------
    async def steer_before_tool(self, *, agent: Any, tool_use: dict[str, Any], **kwargs: Any):
        if tool_use.get("name") != STEERED_TOOL or self.required_option is None:
            return Proceed(reason="not the drafting tool")
        answer = self.stored_answer(agent)
        if answer == "decline":
            self.required_option = "mitigation_trip"
        proposed = normalize_option(str((tool_use.get("input") or {}).get("option", "")))
        if proposed != self.required_option:
            self.guides.append({"proposed": proposed, "required": self.required_option})
            return Guide(
                reason=(
                    f"'{proposed}' is not BART's first feasible option for this outage; "
                    f"call draft_message again with option='{self.required_option}'."
                )
            )
        if self.decision_flags and answer is None:
            self.interrupts.append({"case_key": self.case_key, "flags": self.decision_flags})
            # The vended Interrupt action requires a string reason (pydantic), and the vended handler
            # swallows handler exceptions and lets the tool proceed, so the card goes in as JSON text.
            return Interrupt(reason=json.dumps(self.card or {"flags": self.decision_flags}))
        self.proceeds += 1
        return Proceed(reason="option is BART's first feasible option")
