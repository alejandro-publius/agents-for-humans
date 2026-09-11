"""BeforeToolCall hook: cancel any tool call whose arguments fail a validator.

Built on ``strands.hooks.HookProvider`` and ``BeforeToolCallEvent.cancel_tool`` (verified against
the installed SDK: setting ``cancel_tool`` to a string cancels the call and places that string in
an error tool result, which the model then sees).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

# A validator returns None when the arguments are acceptable, else a short reason.
Validator = Callable[[dict[str, Any]], str | None]


def station_code_validator(known: frozenset[str], *fields: str) -> Validator:
    """Every named field must be a station abbreviation in ``known``."""

    def _validate(args: dict[str, Any]) -> str | None:
        for field in fields:
            value = args.get(field)
            if not isinstance(value, str) or value.upper() not in known:
                return f"{field}={value!r} is not a known station"
        return None

    return _validate


def kb_station_validator(*fields: str) -> Validator:
    """Every named field must be a station abbreviation present in kb/stations."""
    from kb.load import known_abbrs

    return station_code_validator(known_abbrs(), *fields)


def kb_elevator_validator(station_field: str, elevator_field: str) -> Validator:
    """``elevator_field`` must name an elevator that kb/stations lists for ``station_field``."""
    from kb.load import elevator_names, known_abbrs

    def _validate(args: dict[str, Any]) -> str | None:
        station = str(args.get(station_field) or "").upper()
        if station not in known_abbrs():
            return f"{station_field}={args.get(station_field)!r} is not a known station"
        elevator = str(args.get(elevator_field) or "")
        if elevator not in elevator_names(station):
            return f"{elevator_field}={elevator!r} is not an elevator the KB lists for {station}"
        return None

    return _validate


class ArgumentValidatorHook(HookProvider):
    """Cancels tool calls whose arguments fail their registered validator."""

    def __init__(self, validators: dict[str, Validator]) -> None:
        self.validators = dict(validators)
        self.cancelled: list[dict[str, Any]] = []
        self.allowed: list[str] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)

    def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use.get("name", "")
        validator = self.validators.get(name)
        if validator is None:
            return
        reason = validator(event.tool_use.get("input") or {})
        if reason is None:
            self.allowed.append(name)
            return
        event.cancel_tool = f"CANCELLED by ArgumentValidatorHook: {reason}"
        self.cancelled.append({"tool": name, "input": event.tool_use.get("input"), "reason": reason})
