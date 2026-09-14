"""make policy-check POLICY=package.module:callable: the real policy engine against the frozen cases.

Writes results/policy_engine_agreement.json and exits 1 on any disagreement. Without POLICY the
case-backed policy is checked against itself (the plumbing proof: 194 of 194)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.interfaces import fixture_policy, load_cases  # noqa: E402
from le_dispatch.policy_check import RESULTS_PATH, compare, load_policy, render, write_results  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default=None, help="package.module:callable (the real engine's adapter)")
    ap.add_argument("--out", default=str(RESULTS_PATH))
    args = ap.parse_args(argv)
    kb, reference = fixture_policy()
    candidate = load_policy(args.policy) if args.policy else reference
    doc = compare(load_cases(), kb, reference, candidate)
    if not args.policy:
        doc["provenance"]["run"] = "the case-backed policy against itself (plumbing proof; pass --policy)"
        doc["provenance"]["claimable"] = False
    write_results(doc, Path(args.out))
    print(render(doc))
    print(f"wrote {args.out} (claimable: {doc['provenance']['claimable']})")
    return 0 if doc["disagree"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
