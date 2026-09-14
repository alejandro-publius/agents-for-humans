"""make wire-convergence: the convergence study through Strands' real Bedrock adapter, per model id.

Every persona (a belief wrong from the start) times every case in the slice, with a stand-in client that
formats nothing itself: the real adapter builds each request the way it does for that model id (JSON tool
results with a status flag for Anthropic models, text without one for Nova), and the persona reads the
conversation as the model would. Writes results/wire_convergence.json for the 24-case slice the claims pin;
any other case count writes results/wire_convergence_<N>.json beside it unless --out says where, so the
full run on the laptop lands next to the pinned one instead of over it. Nothing is sent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.bedrock_wire import run_wire_convergence  # noqa: E402
from le_dispatch.eval_live import load_models  # noqa: E402
from le_dispatch.interfaces import fixture_policy, load_cases, source_label, write_results_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "wire_convergence.json"
SLICE = 24  # the case count the claims pin; results/wire_convergence.json is always this slice


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=SLICE, help="the first N cases (all 194 take about five minutes)")
    ap.add_argument("--out", default=None, help=f"default: {RESULTS.name}, or wire_convergence_<N>.json off the slice")
    args = ap.parse_args(argv)
    if args.out is None:
        args.out = str(RESULTS if args.cases == SLICE else RESULTS.with_name(f"wire_convergence_{args.cases}.json"))
    kb, policy = fixture_policy()
    cases = load_cases()
    if args.cases:
        cases = cases[: args.cases]
    model_ids = tuple(m.model_id for m in load_models()["models"])
    doc = run_wire_convergence(kb, policy, cases, model_ids)
    out = Path(args.out)
    written = write_results_json(out, doc)
    for model_id, r in doc["per_model"].items():
        print(f"{model_id:<48} converged {r['converged']}/{r['runs']} within {r['max_calls']} calls")
        for line in r["failed"]:
            print(f"  failed: {line}")
    print(
        f"wire convergence: {doc['converged']}/{doc['runs']} runs ({len(cases)} cases x {len(doc['personas'])} "
        f"personas x {len(model_ids)} model ids), max {doc['max_calls']} calls, "
        f"{doc['rejected_by_converse_rules']} requests rejected; {'wrote' if written else 'kept'} {out} "
        f"({source_label()})"
    )
    return 0 if doc["converged"] == doc["runs"] and doc["rejected_by_converse_rules"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
