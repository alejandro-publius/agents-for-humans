"""Structured-output schema for the agent's final plan.

The agent must end every run by calling the ``Plan`` tool (Strands registers a tool named after
this class when ``structured_output_model=Plan``). Code, not the model, later verifies that the
option is feasible and that ``added_minutes`` was computed rather than asserted (B4, B6).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# BART's published order of outage options, best first.
# Source: https://www.bart.gov/guide/accessibility/elevators (scraped into kb/ at B1).
OPTION_ORDER: tuple[str, ...] = (
    "alternate elevator",
    "backtracking",
    "transit",
    "mitigation trip",
    "mitigation shuttle",
)


class Plan(BaseModel):
    """What the rider is told, and why."""

    affected: bool = Field(description="True if the outage blocks this rider's boarding, transfer, or exit.")
    option: str = Field(
        description=f"Recommended option, one of {list(OPTION_ORDER)}, or 'none' if the trip is unaffected."
    )
    steps: list[str] = Field(default_factory=list, description="Concrete steps the rider takes, in order.")
    added_minutes: int | None = Field(
        default=None, description="Extra travel time. Computed by code from schedules, never estimated."
    )
    needs_human_decision: bool = Field(
        default=False, description="True when the rider must choose (for example, request a Mitigation Trip)."
    )
    message: str = Field(description="The message sent to the rider, plain language, under 80 words.")
