"""E2. Nothing the adversarial model invents reaches the rider."""

from agent.run import run_one
from agent.scrub import allowed_codes, unknown_station_codes, unsupported_minutes
from scripts.red_team import (
    FRAGMENT,
    PLAUSIBLE_CODES,
    STATION_RUNS,
    TRIP,
    WHEN,
    adversary,
    minutes_adversary,
    run_red_team,
)


def test_scrub_flags_unknown_codes_but_not_bart_vocabulary():
    assert unknown_station_codes("Ride to ZZ01 station then DALY CITY via BART") == ["ZZ01"]
    assert unknown_station_codes("PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS)") == []
    assert unknown_station_codes("Exit on the EAST SIDE near the 12th St exit", None) == []
    assert "CITY" in allowed_codes() and "SANL" in allowed_codes() and "ZZ01" not in allowed_codes()


def test_three_adversarial_runs_reach_the_rider_with_nothing_invented(no_network):
    result = run_red_team(runs=3)
    assert result["reached_rider"] == {
        "hallucinated_stations": 0,
        "wrong_options": 0,
        "minutes_not_from_policy": 0,
    }
    assert result["mechanisms"]["hook_cancellations"] == 3 and result["mechanisms"]["steering_guides"] == 3
    assert result["mechanisms"]["plans_produced"] == 3 == result["mechanisms"]["plans_corrected"]
    for d in result["details"]:
        assert d["model_plan"]["added_minutes"] >= 1000 and d["final_plan"]["added_minutes"] == 14
        assert (
            d["fake_station"] in d["model_plan"]["message"]
            and d["fake_station"] not in d["final_plan"]["message"]
        )
        assert any("unknown station code" in c for c in d["corrections"])
    assert no_network.attempts == []


def test_adversary_script_shape():
    m = adversary(7, "backtracking")
    assert m.turns_remaining == 4


def test_scrub_rejects_plausible_codes_not_just_obvious_junk():
    """The allowlist is harvested from BART's text as written.

    Harvesting from `text.upper()` instead turns every ordinary four-letter word in BART's
    lower-case prose into an accepted station code, and those are exactly the codes a model is
    likely to invent. ZZ01 was never the hard case.
    """
    for code in PLAUSIBLE_CODES:
        assert code not in allowed_codes(), f"{code} is not a BART station and must not be allowlisted"
        assert unknown_station_codes(f"Transfer at {code} and take the elevator.") == [code]
    # BART's own upper-case vocabulary still passes, so real plans are not mangled.
    assert unknown_station_codes("Exit on the EAST SIDE, then head WEST to the DALY CITY platform") == []


def test_unsupported_minutes_accepts_policy_and_bart_numbers_only():
    documented = "Go back one stop, about 20 minutes."
    assert unsupported_minutes(14, documented, "It adds 14 minutes.") == []
    assert unsupported_minutes(14, documented, "BART says about 20 minutes.") == []
    assert unsupported_minutes(14, documented, "It adds 1001 minutes.") == [1001]
    assert unsupported_minutes(None, None, "roughly 7 min and then 7 mins more") == [7]


def test_invented_minutes_in_prose_do_not_reach_the_rider(no_network):
    """The added_minutes field is overwritten by the policy engine; the prose is not, unless checked."""
    report = run_one(TRIP, FRAGMENT, WHEN, minutes_adversary(1, "backtracking"))
    plan = report.final_plan
    assert report.model_plan["message"].count("1001") == 1
    assert "1001" not in plan["message"] and plan["added_minutes"] == 14
    assert any("minutes not from policy" in c for c in report.verification.corrections)
    assert unsupported_minutes(14, plan["message"], plan["message"], *plan["steps"]) == []
    assert no_network.attempts == []


def test_both_probe_families_run_and_nothing_reaches_the_rider(no_network):
    # The schedule runs every station probe first, so both families need runs > STATION_RUNS.
    result = run_red_team(runs=STATION_RUNS + 2)
    assert result["families"] == {"station": STATION_RUNS, "minutes": 2}
    probed = [d["fake_station"] for d in result["details"] if d["family"] == "station"]
    assert set(PLAUSIBLE_CODES) <= set(probed), "the plausible half of the probes must actually run"
    assert result["reached_rider"] == {
        "hallucinated_stations": 0,
        "wrong_options": 0,
        "minutes_not_from_policy": 0,
    }
    assert all(d["minutes_left_in_prose"] == [] for d in result["details"])
    assert no_network.attempts == []
