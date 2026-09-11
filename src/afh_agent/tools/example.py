"""Example custom tool. Replace with tools for the task your agent handles.

Strands builds the tool schema from the type hints and the Google-style docstring,
so keep both accurate: the model reads the docstring to decide when to call the tool.
"""

from __future__ import annotations

from datetime import date

from strands import tool


@tool
def days_until(date_iso: str, today_iso: str | None = None) -> int:
    """Count the whole days from today until a target date.

    Use this before deciding whether something is due soon. Negative means overdue.

    Args:
        date_iso: Target date in ISO format, e.g. "2026-09-14".
        today_iso: Optional override for "today" in ISO format. Defaults to the real date.

    Returns:
        Number of days from today to the target date (negative if the date has passed).
    """
    target = date.fromisoformat(date_iso)
    today = date.fromisoformat(today_iso) if today_iso else date.today()
    return (target - today).days
