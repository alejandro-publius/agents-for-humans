"""F14: the gates' feedback is actionable. A rule-following model that starts
wrong reaches the policy engine's plan on every case, and a model that
cannot act on feedback fails loudly at the cap (so the metric can fail)."""

from __future__ import annotations

import random

import pytest
from le_dispatch.adaptive import PERSONAS, AdaptiveModel, persona_belief, run_convergence
from le_dispatch.eval_live import BudgetedModel, BudgetExceeded
from le_dispatch.gates import build_agent, prose_findings
from le_dispatch.interfaces import Trip, load_cases
from le_dispatch.messages import is_approved


@pytest.mark.parametrize("persona", PERSONAS)
def test_each_persona_recovers_from_feedback(fixture_stack, persona):
    kb, policy = fixture_stack
    case = load_cases()[7]
    trip = Trip("r", case.station, "EMBR", (case.elevator,))
    d = policy(trip)
    model = AdaptiveModel(persona_belief(persona, d))
    bundle = build_agent(BudgetedModel(model, 12, persona), kb, policy, trip)
    out = bundle.agent(f"Plan my trip. Elevator {case.elevator} at {case.station} is out.")
    plan = out.structured_output
    assert plan.option == d.top_option and plan.added_minutes == d.minutes_for(d.top_option)
    assert plan.station == d.station and plan.elevator == d.elevator
    assert prose_findings(plan.rider_message, kb, d.minutes_for(d.top_option)) == []
    assert is_approved(plan.rider_message, d)  # never a sentence the model wrote alone
    assert model.calls <= 5 and model.repairs


def test_convergence_over_a_slice_matches_the_full_run_shape(fixture_stack):
    kb, policy = fixture_stack
    doc = run_convergence(kb, policy, load_cases()[:10])
    assert doc["runs"] == 90 and doc["converged"] == 90 and doc["not_converged"] == 0
    assert doc["max_calls"] == 5 and doc["provenance"]["claimable"] is False
    assert doc["per_persona"]["everything_wrong"]["calls_histogram"] == {"5": 10}
    assert doc["per_persona"]["injection"]["calls_histogram"] == {"3": 10}
    assert 194 * len(PERSONAS) == 1746


def test_a_model_that_ignores_feedback_hits_the_cap(fixture_stack):
    """The metric can fail: if feedback were not acted on, the run stops at the cap."""
    kb, policy = fixture_stack
    case = load_cases()[3]
    trip = Trip("r", case.station, "EMBR", (case.elevator,))
    d = policy(trip)
    model = AdaptiveModel(persona_belief("wrong_option", d))
    model._repair_from_rejection = lambda text: None  # deaf to the plan gate
    model._read = lambda messages: "plan"  # deaf to the tool result too: keeps sending the wrong plan
    bundle = build_agent(BudgetedModel(model, 6, "deaf"), kb, policy, trip)
    with pytest.raises(BudgetExceeded):
        bundle.agent("Plan my trip.")


def test_prose_findings_fuzz_never_misses_a_wrong_minute_or_foreign_code(fixture_stack):
    """Deterministic fuzz: random sentences with random minutes and codes.
    Every wrong minute and every foreign code is reported; the policy
    engine's minutes and KB codes never are."""
    kb, policy = fixture_stack
    rng = random.Random(2026)
    stations = sorted(kb.stations)
    words = ["take", "the", "elevator", "then", "walk", "to", "platform", "and", "ride", "BART", "via", "Muni"]
    for _ in range(300):
        expected = rng.choice([0, 4, 12, 20, None])
        parts = [rng.choice(words) for _ in range(rng.randint(2, 8))]
        wrong_minutes = [m for m in (rng.choice([1, 5, 13, 45, 99]) for _ in range(rng.randint(0, 2))) if m != expected]
        for m in wrong_minutes:
            parts.insert(rng.randrange(len(parts) + 1), f"about {m} minutes")
        if expected is not None and rng.random() < 0.5:
            parts.insert(rng.randrange(len(parts) + 1), f"{expected} more minutes")
        good_codes = [rng.choice(stations) for _ in range(rng.randint(0, 2))]
        bad_codes = [rng.choice(["ZZZZ", "QQQQ", "XY12", "ABCD"]) for _ in range(rng.randint(0, 2))]
        for c in good_codes + bad_codes:
            parts.insert(rng.randrange(len(parts) + 1), c)
        text = " ".join(parts)
        found = prose_findings(text, kb, expected)
        minute_hits = [f for f in found if "states" in f]
        code_hits = [f for f in found if "names" in f]
        assert len(minute_hits) == len(wrong_minutes), (text, found)
        assert len(code_hits) == len(bad_codes), (text, found)
