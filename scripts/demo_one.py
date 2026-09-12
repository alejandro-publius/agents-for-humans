"""``make demo-one``: one synthetic outage against one synthetic trip on the mock provider.

Prints the policy engine's decision, every mechanism that fired (hook cancellation, steering
guide), the model's Plan, and code's verification. Exits 1 if the final plan's option is not the
policy engine's top feasible option.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agent.core import AgentConfig  # noqa: E402
from agent.mock_model import MockModel  # noqa: E402
from agent.run import resume_run, run_one  # noqa: E402
from evals.run import install_network_guard  # noqa: E402
from policy import Trip  # noqa: E402
from policy.sun import PACIFIC  # noqa: E402

FRAGMENT = "SANL: Platform - SFO/Millbrae/Daly City"  # synthetic outage in BART's documented shape
TRIP = Trip(origin="SANL", dest="EMBR")  # synthetic rider trip
WHEN = datetime(2026, 9, 12, 8, 0, tzinfo=PACIFIC)


NIGHT = datetime(2026, 9, 12, 23, 30, tzinfo=PACIFIC)  # after sunset, past the fixture's last train


def after_dark_demo() -> int:
    """The run pauses on a real Interrupt, the decision card is shown, the rider accepts, it resumes."""
    install_network_guard()
    decisions: dict[str, str] = {}
    cfg = AgentConfig(decisions=decisions)
    report = run_one(TRIP, FRAGMENT, NIGHT, MockModel.from_fixture("demo_one_night"), config=cfg)
    print("== demo-one --after-dark (mock provider, synthetic outage and trip) ==")
    d = report.decision
    flags = d["flags"]
    print(f"policy     : top_option={d['top_option']} after_dark={flags['after_dark']}")
    print(f"             last_train={flags['last_train']}")
    if not report.paused:
        print(f"error      : run did not pause ({report.error})")
        return 1
    card = report.card
    print("PAUSED     : run stopped with stop_reason=interrupt; decision card written for the rider:")
    print(f"             station   {card['station_name']} ({card['station']}), {card['elevator']}")
    print(f"             BART says {card['bart_option']}")
    print(f"             recommend {card['recommended']} (+{card['added_minutes']} min)")
    print(f"             minutes   {card['minutes_basis']}")
    print(f"             flags     {card['flags']}")
    print(f"             source    {card['source_url']} (scraped {card['scraped_at']})")
    for r in card["rejected_options"]:
        print(f"             rejected  {r['option']}: {r['reason']}")
    print("rider      : accept")
    resumed = resume_run(report, "accept")
    print(f"RESUMED    : final plan option={resumed.final_plan['option']} verified={resumed.verification}")
    print(f"remembered : {decisions}")
    cfg2 = AgentConfig(decisions=decisions)
    again = run_one(TRIP, FRAGMENT, NIGHT, MockModel.from_fixture("demo_one_night"), config=cfg2)
    n_int = again.mechanisms["steering_interrupts"]
    print(f"same case  : paused={again.paused} interrupts={n_int} option={again.final_plan['option']}")
    ok = resumed.final_plan["option"] == d["top_option"] and not again.paused
    print(f"RESULT     : pause, resume, remembered: {ok}")
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--trace" in args:
        from agent.tracing import setup_file_tracing

        trace_path = args[args.index("--trace") + 1]
        setup_file_tracing(trace_path)
        print(f"tracing    : every span -> {trace_path}")
    if "--after-dark" in args:
        return after_dark_demo()
    install_network_guard()
    report = run_one(TRIP, FRAGMENT, WHEN, MockModel.from_fixture("demo_one"))
    d = report.decision
    print("== demo-one (mock provider, synthetic outage and trip, synthetic schedule fixture) ==")
    parsed = report.parsed
    print(f"outage     : {report.fragment} -> {parsed['station_abbr']} / {parsed['kb_elevator']}")
    print(f"trip       : {report.trip['origin']} -> {report.trip['dest']} at {report.trip['when']}")
    print(f"policy     : affected={d['affected']} condition={d['condition']} top_option={d['top_option']}")
    for o in d["ranked_options"]:
        flag = "feasible" if o["feasible"] else f"infeasible ({o['reason']})"
        print(f"             #{o['rank']} {o['option']:20} {flag:34} minutes={o['added_minutes']}")
        print(f"                 source: {o['source']}")
    print(f"flags      : after_dark={d['flags']['after_dark']} last_train={d['flags']['last_train']}")
    m = report.mechanisms
    print(f"mechanisms : hook cancelled {m['hook_cancellations']} call(s) {m['hook_cancelled_calls']}")
    print(f"             steering guided {m['steering_guides']} call(s) {m['steering_guide_details']}")
    print(f"model plan : {json.dumps(report.model_plan)}")
    print(f"verified   : {report.verification}")
    print(f"final plan : {json.dumps(report.final_plan)}")
    if report.error:
        print(f"error      : {report.error}")
        return 1
    ok = report.final_plan["option"] == d["top_option"] and report.verification.option_ok
    final_option, top = report.final_plan["option"], d["top_option"]
    print(f"RESULT     : final option {final_option!r} == policy top option {top!r}: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
