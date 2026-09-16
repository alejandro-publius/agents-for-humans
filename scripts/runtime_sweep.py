"""make runtime-sweep: every case through the runtime entrypoint, offline (le_dispatch/runtime_sweep.py).

Five riders per case (daytime; daytime with a note that only gives orders; daytime with a note that names a
real constraint and gives orders too; after dark, never answers; after dark, says no), the learner stand-in
through Strands' real Bedrock adapter, the resilient AgentCore Memory stand-in. Writes
results/runtime_sweep.json; with --agency synthetic, the second agency's cases through the same entrypoint,
results/runtime_sweep_synthetic.json. Nothing is sent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.interfaces import fixture_policy, load_cases, source_label, write_results_json  # noqa: E402
from le_dispatch.runtime_sweep import DEFAULT_MODEL_ID, render, run_sweep  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "runtime_sweep.json"
RESULTS_SYNTHETIC = ROOT / "results" / "runtime_sweep_synthetic.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=0, help="the first N cases (0: all, about a minute)")
    ap.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    ap.add_argument("--out", default=None, help="default results/runtime_sweep.json, or _synthetic.json")
    ap.add_argument(
        "--agency",
        choices=("bart", "synthetic"),
        default="bart",
        help="synthetic: the second agency (le_dispatch/portability.py), other stations, its own option order",
    )
    args = ap.parse_args(argv)
    if args.agency == "synthetic":
        from le_dispatch.portability import synthetic_agency

        kb, cases, policy = synthetic_agency()
        far = tuple(sorted(kb.stations))[:3]
        agency = "the synthetic second agency"
    else:
        kb, policy = fixture_policy()
        cases = load_cases()
        far = None
        agency = "BART"
    if args.cases:
        cases = cases[: args.cases]
    doc = run_sweep(kb, policy, cases, model_id=args.model_id, far_stations=far, agency=agency)
    out = Path(args.out) if args.out else (RESULTS_SYNTHETIC if args.agency == "synthetic" else RESULTS)
    written = write_results_json(out, doc)
    print(render(doc))
    if written:
        print(f"wrote {out} ({source_label() if args.agency == 'bart' else 'synthetic agency'})")
    n = doc["cases"]
    complete = all(
        doc[k] == n
        for k in (
            "daytime_sent",
            "agreement",
            "minutes_agreement",
            "one_message",
            "asked_once",
            "superseded",
            "late_answer",
            "held",
            "held_remembered",
            "forgotten",
            "asked_again",
        )
    )
    return 0 if complete and doc["composed_by_code"] == 0 and not doc["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
