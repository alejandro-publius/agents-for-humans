"""make agentcore-eval-local: run the custom evaluator on real Strands spans, offline.

Every scenario runs through the full stack on a compliant scripted model
with the in-memory OpenTelemetry exporter; the spans are converted to the
evaluator payload shape and scored by le_dispatch/evaluators/option_equality.py.
Writes results/agentcore_eval_local.json (plumbing proof, never a result).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.agentcore_eval import (  # noqa: E402
    LOCAL_RESULTS_PATH,
    run_local_evaluation,
    write_local_results,
)
from le_dispatch.interfaces import FixturePolicy, load_cases, load_kb  # noqa: E402
from le_dispatch.messages import composed_plan  # noqa: E402
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call  # noqa: E402


def compliant_factory(policy):
    def make(case, trip):
        d = policy(trip)
        plan = composed_plan(d)
        return ScriptedModel(
            [
                tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t"),
                plan_call(plan, "p"),
            ]
        )

    return make


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default=None, help="KB export JSON (LE_KB_EXPORT, else the fixture)")
    ap.add_argument("--cases", default=None, help="cases export JSON (LE_CASES_EXPORT, else the fixture)")
    ap.add_argument("--out", default=str(LOCAL_RESULTS_PATH))
    args = ap.parse_args(argv)
    kb = load_kb(args.kb)
    cases = load_cases(args.cases)
    policy = FixturePolicy(cases, kb)
    doc = run_local_evaluation(cases, kb, policy, model_factory=compliant_factory(policy))
    doc["results"] = doc["results"]  # keep per-scenario rows; they are small
    write_local_results(doc, Path(args.out))
    print(
        f"local evaluation on real Strands spans: {doc['pass']}/{doc['scenarios']} PASS, "
        f"option found in {doc['option_found_in']} (claimable: {doc['provenance']['claimable']})"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
