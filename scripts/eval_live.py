"""make eval-live: two models x two modes, 200-call hard cap per entry. Laptop only.

Without credentials this prints the four entries it would run and exits 0.
With credentials it still refuses without --yes. `--stand-in` is the dress
rehearsal: the same path (a real BedrockModel per entry, every case through
deliver(), the merge, the table) with the boto3 client replaced by a
stand-in that plays a model reading the conversation; no credentials, no
network, never a result (the rows go to a separate file, marked stand-in).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch import live  # noqa: E402
from le_dispatch.eval_live import (  # noqa: E402
    RESULTS_PATH,
    credentials_present,
    load_models,
    merge_entries,
    planned_entries,
    run_all,
)
from le_dispatch.interfaces import FixturePolicy, load_cases, load_kb  # noqa: E402


def bedrock_factory(region: str):
    """The live model on the live client configuration (le_dispatch/live.py): botocore's own retries off, a
    read timeout; Strands' bounded strategy goes on every agent (`run_all(retry_strategy=...)`)."""

    def make(model):
        return live.model(model.model_id, region)  # laptop only; the call needs credentials

    return make


def stand_in_factory(region: str):
    """The same BedrockModel, its client replaced by the learner stand-in (le_dispatch.bedrock_wire)."""

    def make(model):
        from le_dispatch.bedrock_wire import wired_learner_model

        return wired_learner_model(model.model_id, region)

    return make


STAND_IN_OUT = Path(tempfile.gettempdir()) / "le-eval-live-stand-in.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="actually call Bedrock (laptop)")
    ap.add_argument("--kb", default=None, help="KB export JSON (LE_KB_EXPORT, else the fixture)")
    ap.add_argument("--cases", default=None, help="cases export JSON (LE_CASES_EXPORT, else the fixture)")
    ap.add_argument("--out", default=str(RESULTS_PATH))
    ap.add_argument(
        "--cap",
        type=int,
        default=None,
        help="calls per entry (default from evals/live_models.json); an enforced case needs at least two calls, "
        "so 200 covers about 100 cases and 1200 covers all 194 with room for retries",
    )
    ap.add_argument("--limit-cases", type=int, default=None, help="run the first N cases only (a cheaper run)")
    ap.add_argument(
        "--stand-in",
        action="store_true",
        help="the dress rehearsal: the live path with a stand-in client, no credentials needed, never a result",
    )
    args = ap.parse_args(argv)

    config = load_models()
    if args.stand_in:
        for m in config["models"]:
            m.provider = "stand-in"
        if args.out == str(RESULTS_PATH):
            args.out = str(STAND_IN_OUT)  # never into the file the README table reads
    if args.cap is not None:
        config["hard_cap_calls_per_entry"] = args.cap
    cap = int(config["hard_cap_calls_per_entry"])
    n_cases = args.limit_cases or len(load_cases(args.cases))
    print("eval-live entries:")
    for line in planned_entries(config):
        print("  " + line)
    print(
        f"  cases per entry: {n_cases}; the cap of {cap} calls covers about {cap // 2} cases at two calls each "
        f"(an enforced retry costs one more); pass --cap {n_cases * 6} to run every case with room for retries"
    )
    if args.stand_in:
        print("\nstand-in: the live path through the real Bedrock adapter with a stand-in client; nothing called")
    elif not credentials_present():
        print("\nno credentials in the environment: dry run, nothing called")
        return 0
    elif not args.yes:
        print("\ncredentials present but --yes not given: nothing called")
        return 0
    kb = load_kb(args.kb)
    cases = load_cases(args.cases)
    if args.limit_cases:
        cases = cases[: args.limit_cases]
    policy = FixturePolicy(cases, kb)  # the laptop swaps in the real policy engine
    factory = stand_in_factory(config["region"]) if args.stand_in else bedrock_factory(config["region"])
    entries = run_all(config, cases, kb, policy, model_factory=factory, retry_strategy=live.retry_strategy())
    merge_entries(entries, Path(args.out))
    for e in entries:
        print(
            f"{e['model_name']:<10} {e['mode']:<12} {e['agree']}/{e['cases']} ({e['agreement_pct']}%) "
            f"calls {e['calls_used']} tokens {e['tokens_used']} composed_by_code {e['composed_by_code']}"
            + (f"\n  stopped early: {e['stopped_early']}" if e.get("stopped_early") else "")
            + ("" if e.get("claimable") else "\n  not claimable: " + not_claimable_reason(e))
        )
    print(f"wrote {args.out}; then make results-table" if not args.stand_in else f"wrote {args.out} (stand-in rows)")
    return 0


def not_claimable_reason(entry: dict) -> str:
    if entry.get("provider") == "stand-in":
        return "a stand-in client stood in for Bedrock; plumbing proof only"
    return "the fixture cases were used; set the exports"


if __name__ == "__main__":
    raise SystemExit(main())
