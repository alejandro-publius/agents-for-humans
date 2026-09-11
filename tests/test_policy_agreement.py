"""B7. Policy-agreement cases come straight from the KB; mock mode proves plumbing; budget is honored."""

import json
from datetime import datetime

from agent.mock_model import MockModel
from agent.run import run_condition
from evals import run as evals_run
from evals.gen_policy_cases import OUT, build_cases
from kb.load import load_stations
from policy import Trip
from policy.sun import PACIFIC


def test_generator_covers_every_documented_option_once():
    cases = build_cases()
    documented = sum(len(s["documented_outage_options"]) for s in load_stations().values())
    assert len(cases) == documented == 194
    assert len({c["name"] for c in cases}) == len(cases)
    committed = json.loads(OUT.read_text())
    assert [c["name"] for c in committed["cases"]] == [c["name"] for c in cases]
    assert {c["label"] for c in cases} <= {"alternate_elevator", "backtracking", "transit", "mitigation_trip"}


def test_labels_are_the_kb_labels_not_tuned():
    stations = load_stations()
    for c in build_cases():
        elevators = stations[c["input"]["station"]]["elevators"]
        elevator = next(e for e in elevators if e["name"] == c["input"]["elevator"])
        opt = next(o for o in elevator["outage_options"] if o["situation"] == c["input"]["situation"])
        assert c["label"] == opt["option_label"]


def test_mock_echo_agrees_with_label_and_code_agrees_with_policy():
    case = build_cases()[0]
    inp = case["input"]
    model = MockModel(inp["mock_turns"], name=case["name"])
    report = run_condition(
        Trip(inp["trip"]["origin"], inp["trip"]["dest"]),
        inp["station"],
        inp["elevator"],
        inp["situation"],
        datetime(2026, 9, 12, 8, 0, tzinfo=PACIFIC),
        model,
    )
    assert report.error is None
    assert report.model_plan["option"] == case["label"]
    assert report.decision["top_option"] == case["label"]
    assert report.final_plan["option"] == case["label"]


def test_budget_skips_cases_for_live_providers_only():
    suite = {
        "suite": "policy_agreement",
        "description": "x",
        "output_of": "policy_agreement",
        "cases": build_cases()[:3],
    }
    result = evals_run.run_suite(suite, provider="mock", ablate=False, max_model_calls=1)
    assert result["cases_run"] == 3 and result["baselines"]["cases_skipped_for_budget"] == 0
    assert result["mode"] == "mock" and result["agreement_pct"] == 100.0
