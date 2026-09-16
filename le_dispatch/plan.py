"""The plan the agent must produce, and the one tool it may call to draft it.

The Plan is the structured output of the run (Strands structured output tool
named after the class). The model fills it in; code checks every field
against the policy decision before it can reach the rider (see gates.py).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from strands import tool

from .interfaces import KBSet, PolicyCallable, Trip
from .messages import approved_messages


class Plan(BaseModel):
    """Final plan for one rider and one trip. Every field is checked by code."""

    station: str = Field(description="Station abbreviation where the outage bites, from the KB")
    elevator: str = Field(description="Elevator id that is out, from the KB")
    option: str = Field(
        description="BART's sanctioned option label: the policy_top_option returned by draft_plan, never another"
    )
    added_minutes: int | None = Field(
        default=None, description="Minutes added: the added_minutes returned by draft_plan, never computed"
    )
    rider_message: str = Field(
        description="One of the approved_messages returned by draft_plan, copied verbatim; nothing else is accepted"
    )
    status: Literal["send", "hold"] = Field(
        default="send",
        description="send: deliver the plan. hold: the rider declined this reroute when asked; keep the plan on file",
    )


def make_tools(kb: KBSet, policy: PolicyCallable, trip: Trip) -> list[Any]:
    """Tools for one run. draft_plan is the only write-shaped tool; its output
    comes from the policy engine, so minutes and rankings are never model math."""

    @tool
    def draft_plan(station: str, elevator: str, option: str) -> str:
        """Draft a plan for the rider's trip given the station, the elevator that is out, and BART's option label.

        Args:
            station: Station abbreviation from the knowledge base (for example DELN).
            elevator: Elevator id from the knowledge base (for example DELN-E1).
            option: BART option label: alternate_elevator, backtracking, transit, mitigation_trip, mitigation_shuttle.
        """
        decision = policy(trip)
        draft = {
            "station": station,
            "elevator": elevator,
            "option": option,
            "added_minutes": decision.minutes_for(option),
            "policy_top_option": decision.top_option,
            "source_url": decision.source_url,
            "flags": decision.flags,
            # the sentences the rider may receive, composed by code; the Plan's rider_message must be one of them
            "approved_messages": approved_messages(decision),
        }
        return json.dumps(draft)

    return [draft_plan]


PLAN_TOOL_NAME = "draft_plan"
