"""Steering handler: rewrite the model's response when a policy check fails.

Built on ``strands.interventions.InterventionHandler.after_model_call`` returning ``Transform``
(verified against the installed SDK: the registry calls ``Transform.apply(event)`` and the event
loop then emits the same, now-mutated, message object).

Block A ships one generic policy: the response's recommended option must be the option that code
says is the highest-ranked feasible one. B6 feeds that option from the policy engine.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from strands.hooks import AfterModelCallEvent
from strands.interventions import InterventionHandler, Proceed, Transform

from agent.schema import OPTION_ORDER

# A policy check returns None when the text is acceptable, else a short violation reason.
PolicyCheck = Callable[[str], str | None]
Rewrite = Callable[[str, str], str]


def first_option_mentioned(text: str) -> str | None:
    """The option the response recommends: the earliest-mentioned option name in the text."""
    lowered = text.lower()
    hits = [(lowered.find(opt), opt) for opt in OPTION_ORDER if opt in lowered]
    return min(hits)[1] if hits else None


def option_order_policy(required_option: str | None) -> PolicyCheck:
    """The response must recommend ``required_option`` (code's top feasible option)."""

    def _check(text: str) -> str | None:
        if required_option is None:
            return None
        recommended = first_option_mentioned(text)
        if recommended is None:
            return f"response names no option; policy requires {required_option!r}"
        if recommended != required_option:
            return f"response recommends {recommended!r} but the first feasible option is {required_option!r}"
        return None

    return _check


def option_order_rewrite(required_option: str | None) -> Rewrite:
    def _rewrite(original: str, reason: str) -> str:
        return (
            f"{(required_option or 'none').capitalize()} is the first feasible option under BART's "
            f"published outage order. Draft withheld by policy: {reason}."
        )

    return _rewrite


def _message_text(message: dict[str, Any]) -> str:
    return " ".join(b["text"] for b in message.get("content", []) if isinstance(b, dict) and "text" in b)


def _set_message_text(message: dict[str, Any], text: str) -> None:
    others = [b for b in message.get("content", []) if not (isinstance(b, dict) and "text" in b)]
    message["content"] = [{"text": text}, *others]


class SteeringHandler(InterventionHandler):
    """Rewrites a non-compliant final response in place; records every rewrite for evals."""

    name = "policy-steering"

    def __init__(self, check: PolicyCheck, rewrite: Rewrite) -> None:
        self.check = check
        self.rewrite = rewrite
        self.rewrites: list[dict[str, str]] = []
        self.passed: int = 0

    def after_model_call(self, event: AfterModelCallEvent, **kwargs: Any):
        if event.stop_response is None:
            return Proceed()
        message = event.stop_response.message
        text = _message_text(message)
        if not text.strip():
            return Proceed()
        reason = self.check(text)
        if reason is None:
            self.passed += 1
            return Proceed()
        replacement = self.rewrite(text, reason)
        self.rewrites.append({"original": text, "reason": reason, "rewritten": replacement})

        def apply(ev: Any) -> None:
            _set_message_text(ev.stop_response.message, replacement)

        return Transform(apply=apply, reason=reason)
