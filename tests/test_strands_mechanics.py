"""Standing proof of the three Strands mechanisms on the real agent loop, offline. Keep green.

A scripted model (a) drafts with an elevator that is not in the KB, (b) drafts with the wrong
option, (c) drafts correctly and submits a Plan. Expect exactly one hook cancellation, one
steering Guide, one valid Plan, and zero network attempts.
"""

from datetime import datetime

from agent.mock_model import MockModel
from agent.run import run_one
from policy import Trip
from policy.sun import PACIFIC

ELEVATOR = "PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS)"
FRAGMENT = "SANL: Platform - SFO/Millbrae/Daly City"
WHEN = datetime(2026, 9, 12, 8, 0, tzinfo=PACIFIC)
STEPS = ["Take the Platform 1 elevator to the opposite platform.", "Ride one stop to Bay Fair and come back."]


def _draft(option: str, elevator: str = ELEVATOR) -> dict:
    return {
        "type": "tool_use",
        "name": "draft_message",
        "input": {
            "option": option,
            "station_abbr": "SANL",
            "elevator": elevator,
            "steps": STEPS,
            "added_minutes": 14,
        },
    }


PLAN = {
    "type": "tool_use",
    "name": "Plan",
    "input": {
        "affected": True,
        "option": "backtracking",
        "steps": STEPS,
        "added_minutes": 14,
        "message": "ok",
    },
}


def test_hook_cancel_then_steering_guide_then_valid_plan(no_network):
    model = MockModel(
        [
            _draft("backtracking", elevator="PLATFORM 9 ELEVATOR"),
            _draft("mitigation_shuttle"),
            _draft("backtracking"),
            PLAN,
        ]
    )
    report = run_one(Trip("SANL", "EMBR"), FRAGMENT, WHEN, model)

    assert report.error is None
    assert report.mechanisms["hook_cancellations"] == 1
    cancelled_reason = report.mechanisms["hook_cancelled_calls"][0]["reason"]
    assert cancelled_reason.startswith("elevator='PLATFORM 9 ELEVATOR' is not")
    assert report.mechanisms["steering_guides"] == 1
    guides = report.mechanisms["steering_guide_details"]
    assert guides == [{"proposed": "mitigation_shuttle", "required": "backtracking"}]
    assert report.model_plan["option"] == "backtracking"
    assert report.verification.option_ok and report.verification.minutes_ok
    assert report.final_plan["option"] == report.decision["top_option"] == "backtracking"
    assert model.turns_remaining == 0
    assert no_network.attempts == []


def test_code_corrects_a_plan_that_disagrees_with_policy(no_network):
    """Even if the model slips past steering (ablation), the final plan is code's."""
    from agent.core import AgentConfig

    bad_plan = {**PLAN, "input": {**PLAN["input"], "option": "mitigation_shuttle", "added_minutes": 99}}
    model = MockModel([_draft("mitigation_shuttle"), bad_plan])
    report = run_one(Trip("SANL", "EMBR"), FRAGMENT, WHEN, model, config=AgentConfig.ablated())
    assert report.mechanisms["ablated"] and report.mechanisms["steering_guides"] == 0
    assert report.model_plan["option"] == "mitigation_shuttle"
    assert report.final_plan["option"] == "backtracking" and report.final_plan["added_minutes"] == 14
    assert not report.verification.option_ok and len(report.verification.corrections) == 2


# --- E1: real Interrupts for after-dark and last-train decisions -------------------------------

NIGHT = datetime(2026, 9, 12, 23, 30, tzinfo=PACIFIC)  # after sunset and past the last train in the fixture


def _night_model():
    # At night backtracking is infeasible (last train), so the policy top option is transit.
    draft = {
        "type": "tool_use",
        "name": "draft_message",
        "input": {
            "option": "transit",
            "station_abbr": "SANL",
            "elevator": ELEVATOR,
            "steps": ["Take an AC Transit bus to Bay Fair."],
            "added_minutes": None,
        },
    }
    plan = {
        "type": "tool_use",
        "name": "Plan",
        "input": {"affected": True, "option": "transit", "steps": draft["input"]["steps"], "message": "bus"},
    }
    return MockModel([draft, plan])


def test_after_dark_case_interrupts_once_then_resumes_and_remembers(tmp_path, no_network):
    from agent.core import AgentConfig
    from agent.run import resume_run

    decisions: dict[str, str] = {}
    cfg = AgentConfig(decisions=decisions, session_id="rider-night", session_dir=str(tmp_path))

    model = _night_model()
    report = run_one(Trip("SANL", "EMBR"), FRAGMENT, NIGHT, model, config=cfg)

    # exactly one Interrupt: the run paused before draft_message ran, no plan yet
    assert report.paused and report.mechanisms["steering_interrupts"] == 1
    assert report.final_plan is None and model.turns_consumed == 1
    import json

    card = report.card
    assert json.loads(report.interrupt["reason"]["message"]) == card, "the card travels inside the Interrupt"
    assert card["flags"] == ["after_dark", "last_train"]
    assert card["recommended"] == "transit" and card["source_url"].endswith("/stations/SANL/accessible")
    rejected = {r["option"] for r in card["rejected_options"]}
    assert rejected == {"backtracking", "mitigation_trip", "mitigation_shuttle"}
    assert any("last train" in r["reason"] for r in card["rejected_options"])

    # resuming with "accept" yields a plan whose option is the policy top option
    resumed = resume_run(report, "accept")
    assert not resumed.paused and resumed.final_plan["option"] == "transit"
    assert resumed.verification.option_ok and model.turns_remaining == 0
    assert decisions == {card["case_key"]: "accept"}

    # a second identical case, new agent, same session id: Proceed, no Interrupt
    cfg2 = AgentConfig(decisions={}, session_id="rider-night", session_dir=str(tmp_path))
    model2 = _night_model()
    again = run_one(Trip("SANL", "EMBR"), FRAGMENT, NIGHT, model2, config=cfg2)
    assert not again.paused and again.mechanisms["steering_interrupts"] == 0
    assert again.final_plan["option"] == "transit" and model2.turns_remaining == 0
    assert no_network.attempts == []


def test_daytime_case_never_interrupts(no_network):
    model = MockModel([_draft("backtracking"), PLAN])
    report = run_one(Trip("SANL", "EMBR"), FRAGMENT, WHEN, model)
    assert not report.paused and report.mechanisms["steering_interrupts"] == 0 and report.card is None
