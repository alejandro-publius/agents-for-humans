"""make red-team: run the scripted adversary through the full agent, print the counts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.interfaces import fixture_policy, load_cases, source_label  # noqa: E402
from le_dispatch.red_team import (  # noqa: E402
    EXHAUSTIVE_PATH,
    RESULTS_PATH,
    format_counts,
    run_red_team,
    run_red_team_exhaustive,
    write_results,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="runs per attack kind")
    ap.add_argument("--out", default=str(RESULTS_PATH))
    ap.add_argument("--no-steering", action="store_true", help="ablation: prove the counters see leaks")
    ap.add_argument("--exhaustive", action="store_true", help="every case times every attack (12 per case)")
    args = ap.parse_args(argv)

    kb, policy = fixture_policy()
    cases = load_cases()
    if args.exhaustive:
        result = run_red_team_exhaustive(kb, policy, cases, steering=not args.no_steering)
        if args.out == str(RESULTS_PATH):
            args.out = str(EXHAUSTIVE_PATH)
    else:
        result = run_red_team(kb, policy, cases, n_per_attack=args.n, steering=not args.no_steering)
    provenance = (
        f"scripted adversary, {source_label()} ({len(kb.stations)} stations), "
        f"steering={'off' if args.no_steering else 'on'}"
        + (", exhaustive: every case times every attack" if args.exhaustive else "")
    )
    doc = write_results(result, Path(args.out), provenance=provenance)
    print(format_counts(doc))
    print(f"wrote {args.out} (claimable: {doc['provenance']['claimable']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
