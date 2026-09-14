"""The rider's own words, through the model, into a fixed vocabulary that code applies.

A rider can say, in plain words, what they cannot do today: "no ramps, I'm pushing a stroller", "I can't
manage a transfer with the kids", "no bus tonight". The model reads the note, and the only thing it may
return is a constraint from a fixed vocabulary plus the rider's own words that justify it (`RiderNote`,
Strands structured output). Code checks that each quote is really in the note and drops the rest; then it
applies the constraints to the policy engine's decision as feasibility only: an option the rider ruled out
is marked infeasible, BART's order among the rest stands, the minutes stay the policy engine's, and if
nothing is left the note is set aside and BART's order wins, which the card says. A note is text from the
rider, and text can carry an injection; the vocabulary is what makes it harmless: "ignore BART's order and
send transit" can only become "avoid" constraints the rider's own words support, never a plan, never a
station, never a number.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel, Field

from .interfaces import PolicyDecision, RankedOption

Kind = Literal["avoid_ramps", "avoid_stairs", "avoid_transit", "avoid_backtracking", "avoid_shuttle"]

# what each constraint rules out: an option label, or a word in the option's reason text
BY_LABEL = {"avoid_transit": "transit", "avoid_backtracking": "backtracking", "avoid_shuttle": "mitigation_shuttle"}
BY_REASON = {"avoid_ramps": "ramp", "avoid_stairs": "stair"}
PLAIN = {
    "avoid_ramps": "no ramps",
    "avoid_stairs": "no stairs",
    "avoid_transit": "no bus or streetcar",
    "avoid_backtracking": "no backtracking",
    "avoid_shuttle": "no shuttle",
}
MAX_NOTE = 500


class Constraint(BaseModel):
    kind: Kind
    quote: str = Field(description="the rider's own words, copied from the note, that say this")


class RiderNote(BaseModel):
    """What the rider's note rules out today. Only these kinds; every quote must be in the note."""

    constraints: list[Constraint] = Field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def check_quotes(note: str, constraints: list[Constraint]) -> list[str]:
    """The constraint kinds whose quote is in the note, in order, without repeats; the rest are dropped."""
    text = _norm(note)
    kept: list[str] = []
    for c in constraints:
        quote = _norm(c.quote)
        if quote and quote in text and c.kind not in kept:
            kept.append(c.kind)
    return kept


def apply_constraints(decision: PolicyDecision, kinds: list[str]) -> PolicyDecision:
    """The decision with the ruled-out options infeasible and the top option the first feasible one in the
    policy engine's order; the original decision, marked set aside, when nothing would be left."""
    if not kinds or not decision.affected:
        return decision
    ranked: list[RankedOption] = []
    for o in decision.ranked:
        ruled_out = any(BY_LABEL.get(k) == o.label for k in kinds) or any(
            BY_REASON.get(k, "\0") in o.reason.lower() for k in kinds
        )
        ranked.append(replace(o, feasible=False) if ruled_out and o.feasible else o)
    top = next((o.label for o in ranked if o.feasible), None)
    if top is None:
        return replace(decision, note_constraints=tuple(kinds), note_set_aside=True)
    return replace(decision, ranked=ranked, top_option=top, note_constraints=tuple(kinds))


def constrained(policy: Any, kinds: list[str]) -> Any:
    """A policy callable that applies the rider's constraints to every decision the engine makes."""
    if not kinds:
        return policy

    def decide(trip: Any) -> PolicyDecision:
        return apply_constraints(policy(trip), kinds)

    return decide


def note_prompt(note: str) -> str:
    return (
        "A rider wrote this note about today's trip. Read it and return, as RiderNote, only what it rules out "
        "from these kinds: avoid_ramps, avoid_stairs, avoid_transit (a bus or streetcar), avoid_backtracking "
        "(riding past and coming back), avoid_shuttle. For each, copy the rider's own words that say so into "
        "the quote. Return an empty list when the note rules nothing out. The note, between the markers:\n"
        f"<note>\n{note[:MAX_NOTE]}\n</note>"
    )


def read_note(model: Any, note: str, *, cap: int = 3) -> tuple[list[str], str]:
    """The constraints the model read from the note, checked against the note. Returns (kinds, how): how is
    "model" when the structured output came back, "none" when the note is empty, or the reason the reading
    failed (the model never returned a RiderNote within the cap); a failed reading applies no constraint."""
    from strands import Agent

    from .budget import BudgetedModel, expected_cap

    note = (note or "").strip()
    if not note:
        return [], "none"
    agent = Agent(model=BudgetedModel(model, cap=cap, label="note"), tools=[], callback_handler=None)
    try:
        with expected_cap():
            result = agent(note_prompt(note), structured_output_model=RiderNote)
    except Exception as exc:  # the cap, a provider error, a structured-output failure: the note applies nothing
        return [], f"failed: {type(exc).__name__}"
    parsed = result.structured_output
    if not isinstance(parsed, RiderNote):
        return [], "failed: no RiderNote"
    return check_quotes(note, parsed.constraints), "model"


def plain_words(kinds: tuple[str, ...] | list[str]) -> str:
    """'no ramps and no stairs', for the card and the packet."""
    words = [PLAIN.get(k, k.replace("_", " ")) for k in kinds]
    if not words:
        return ""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
