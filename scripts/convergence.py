"""make convergence: is the gates' feedback actionable? A rule-following model
that starts wrong (nine personas) must reach the policy engine's plan on
every frozen case within the call cap. Writes results/adaptive_convergence.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.adaptive import RESULTS_PATH, run_convergence  # noqa: E402
from le_dispatch.interfaces import fixture_policy, load_cases, write_results_json  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RESULTS_PATH))
    ap.add_argument("--cap", type=int, default=12)
    args = ap.parse_args(argv)
    kb, policy = fixture_policy()
    doc = run_convergence(kb, policy, load_cases(), cap=args.cap)
    written = write_results_json(Path(args.out), doc)
    print(
        f"convergence: {doc['converged']}/{doc['runs']} runs reached the policy engine's plan, "
        f"max {doc['max_calls']} model calls"
    )
    for p, r in doc["per_persona"].items():
        print(
            f"  {p:<18} converged {r['converged']}/{r['cases']}  max {r['max_calls']}  "
            f"mean {r['mean_calls']}  hist {r['calls_histogram']}"
        )
    if written:
        print(f"wrote {args.out} (claimable: {doc['provenance']['claimable']})")
    return 0 if doc["not_converged"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
