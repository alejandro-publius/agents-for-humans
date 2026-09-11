"""Agent factory. Everything about *how* the agent behaves lives here."""

from __future__ import annotations

from typing import Any

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.session import FileSessionManager
from strands_tools import current_time

from afh_agent.config import Settings, load_settings
from afh_agent.models import build_model
from afh_agent.tools import DOMAIN_TOOLS

AGENT_NAME = "afh-agent"

SYSTEM_PROMPT = """\
You are a background agent that takes a repetitive task off a person's plate and handles it end to end.

Operating rules:
1. Work autonomously. Use your tools to gather facts before acting; never guess at data a tool can fetch.
2. Make the safe, reversible calls yourself.
3. Surface to the human only when a decision genuinely needs their judgment: money above a threshold,
   anything irreversible, or ambiguous intent. When you do, state the decision in one sentence and
   give the options.
4. When you finish, report what you did and what (if anything) still needs the human, in three lines or fewer.
"""


def build_agent(
    *,
    model: Any | None = None,
    tools: list[Any] | None = None,
    session_id: str | None = None,
    settings: Settings | None = None,
    system_prompt: str = SYSTEM_PROMPT,
) -> Agent:
    """Return a configured Strands Agent.

    Args:
        model: A strands Model instance. Defaults to the provider chosen by environment variables.
        tools: Tool list. Defaults to the domain tools plus a few generic ones from strands_tools.
        session_id: If set, conversation state persists on disk under settings.session_dir so the
            agent can resume across runs (useful for cron-style background execution).
        settings: Explicit Settings; defaults to load_settings().
        system_prompt: Override the default operating rules (tests and experiments).
    """
    settings = settings or load_settings()
    model = model if model is not None else build_model(settings)
    tools = tools if tools is not None else [*DOMAIN_TOOLS, current_time]

    session_manager = (
        FileSessionManager(session_id=session_id, storage_dir=settings.session_dir) if session_id else None
    )

    return Agent(
        name=AGENT_NAME,
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        conversation_manager=SlidingWindowConversationManager(window_size=40),
        session_manager=session_manager,
        callback_handler=None,  # quiet by default; the CLI streams output itself
    )
