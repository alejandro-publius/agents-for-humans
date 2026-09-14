"""A hard cap on model calls, wrapped around any Strands Model.

Why a wrapper and not only Strands' turn limit: in strands-agents 1.55.1
the after-model retry loop (a steering Guide sets AfterModelCallEvent.retry)
is unbounded and runs inside one turn, so a model that keeps producing a
rejected plan would be re-called without limit and `limits={"turns": n}`
would never fire. Every agent built by `build_agent` therefore carries a
per-run cap; when it trips, the delivery layer composes the plan in code.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import Any

from strands.models.model import Model


@contextlib.contextmanager
def expected_cap() -> Iterator[None]:
    """The SDK logs a cap trip as an event-loop ERROR; it is our expected control
    path (the delivery layer records it), so keep the log clean while it runs."""
    logger = logging.getLogger("strands.event_loop.event_loop")
    level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(level)


class BudgetExceeded(RuntimeError):
    pass


class BudgetedModel(Model):
    """Counts model calls and raises BudgetExceeded at the cap."""

    def __init__(self, inner: Model, cap: int, label: str = ""):
        self.inner = inner
        self.cap = cap
        self.calls = 0
        self.label = label

    def update_config(self, **kwargs: Any) -> None:
        self.inner.update_config(**kwargs)

    def get_config(self) -> Any:
        return self.inner.get_config()

    @property
    def config(self) -> Any:
        """Strands reads model.config["model_id"] for the trace attributes when the attribute exists;
        expose the wrapped model's so a live run's spans and evidence packet carry the real model id."""
        inner_config = getattr(self.inner, "config", None)
        return inner_config if inner_config is not None else self.inner.get_config()

    def structured_output(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - tool path is used
        return self.inner.structured_output(*args, **kwargs)

    def stream(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
        if self.calls >= self.cap:
            raise BudgetExceeded(f"{self.label}: hard cap of {self.cap} model calls reached")
        self.calls += 1
        return self.inner.stream(sendable_turns(messages), *args, **kwargs)


SEPARATOR_TEXT = "Tool result received."  # the neutral assistant turn Strands' BedrockModel inserts (its #1223)


def sendable_turns(messages: Any) -> Any:
    """Request-local: the conversation as Bedrock's Converse API accepts it at the first attempt.

    Two passes. Adjacent user text turns are folded into one (a second Guide
    in a row); a tool-result turn followed by a user text turn gets the SDK's
    own neutral assistant turn between them, ahead of time. The SDK inserts
    that turn only after Bedrock has rejected a request once per process and
    model id; doing it here costs nothing on a model that would have accepted
    the request and saves the rejected round trip on one that would not
    (measured in docs/evidence/bedrock-wire.md)."""
    return separate_tool_result_turns(merge_adjacent_user_turns(messages))


def separate_tool_result_turns(messages: Any) -> Any:
    """The same transformation as strands.models.bedrock.BedrockModel._separate_tool_result_turns, applied
    before the adapter sees the request: a neutral assistant turn between a user turn made only of tool
    results and a following user turn with none. Idempotent; the input is not mutated."""
    if not isinstance(messages, list):
        return messages
    out: list[Any] = []
    for message in messages:
        if (
            out
            and isinstance(message, dict)
            and isinstance(out[-1], dict)
            and message.get("role") == "user"
            and out[-1].get("role") == "user"
        ):
            previous = out[-1].get("content", [])
            current = message.get("content", [])
            if (
                previous
                and all(isinstance(b, dict) and "toolResult" in b for b in previous)
                and current
                and all(isinstance(b, dict) and "toolResult" not in b for b in current)
            ):
                out.append({"role": "assistant", "content": [{"text": SEPARATOR_TEXT}]})
        out.append(message)
    return out


def merge_adjacent_user_turns(messages: Any) -> Any:
    """Request-local: fold consecutive user text turns into one user turn.

    A steering Guide after the model discards the assistant response and
    appends the reason as a user turn; a second Guide in a row therefore
    leaves two adjacent user turns in the conversation. Bedrock's Converse
    API requires roles to alternate, and Strands' BedrockModel separates a
    tool-result turn from a following user turn (its #1223) but not two text
    turns. Folding them here keeps every retry sendable. The persisted
    conversation (agent.messages) is not touched; only what the wrapped model
    receives is. A turn that carries a toolResult is never folded into;
    `separate_tool_result_turns` handles that pair."""
    if not isinstance(messages, list):
        return messages
    folded: list[Any] = []
    for message in messages:
        if (
            folded
            and isinstance(message, dict)
            and isinstance(folded[-1], dict)
            and message.get("role") == "user"
            and folded[-1].get("role") == "user"
            and not any("toolResult" in b for b in folded[-1].get("content", []) if isinstance(b, dict))
            and not any("toolResult" in b for b in message.get("content", []) if isinstance(b, dict))
        ):
            merged = dict(folded[-1])
            merged["content"] = list(folded[-1].get("content", [])) + list(message.get("content", []))
            folded[-1] = merged
        else:
            folded.append(message)
    return folded
