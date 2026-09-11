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

from agent.mock_model import MockModel  # noqa: E402
from agent.run import run_one  # noqa: E402
from evals.run import install_network_guard  # noqa: E402
from policy import Trip  # noqa: E402
from policy.sun import PACIFIC  # noqa: E402

FRAGMENT = "SANL: Platform - SFO/Millbrae/Daly City"  # synthetic outage in BART's documented shape
TRIP = Trip(origin="SANL", dest="EMBR")  # synthetic rider trip
WHEN = datetime(2026, 9, 12, 8, 0, tzinfo=PACIFIC)


def main() -> int:
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
