"""make agentcore-eval: export the dataset and print the plan (--dry-run, default).

python scripts/agentcore_eval.py --dry-run
python scripts/agentcore_eval.py --apply --yes --agent-runtime-arn arn:...   # laptop only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.agentcore_eval import (  # noqa: E402
    DEFAULT_REGION,
    credentials_present,
    plan,
    run_apply,
    write_exports,
)
from le_dispatch.api_shapes import check_calls, service_models_available  # noqa: E402
from le_dispatch.interfaces import FixturePolicy, load_cases, load_kb  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--kb", default=None, help="KB export JSON (LE_KB_EXPORT, else the fixture)")
    ap.add_argument("--cases", default=None, help="cases export JSON (LE_CASES_EXPORT, else the fixture)")
    ap.add_argument("--region", default=DEFAULT_REGION)
    ap.add_argument("--agent-runtime-arn", default="${AGENT_RUNTIME_ARN}")
    ap.add_argument("--model-id", default="${MODEL_ID}")
    args = ap.parse_args(argv)

    kb = load_kb(args.kb)
    cases = load_cases(args.cases)
    policy = FixturePolicy(cases, kb)  # the laptop swaps in the real policy engine (INTEGRATION step 3)
    dataset, stats = write_exports(cases, kb, policy)
    print(f"wrote evals/agentcore/dataset.json ({stats['scenarios']} scenarios) and evaluators.json")
    p = plan(dataset, region=args.region, agent_runtime_arn=args.agent_runtime_arn, model_id=args.model_id)
    if args.apply:
        if not credentials_present():
            print("no AWS credentials in the environment; printing the plan instead")
            print(p.render())
            return 2
        run_apply(p, yes=args.yes)
        return 0
    print(p.render())
    if service_models_available():
        problems = check_calls(p.api_calls)
        if problems:
            print("\nservice-model check FAILED (botocore would reject these calls):")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print(f"\nservice-model check: every call above is well formed ({len(p.api_calls)} call shapes, botocore)")
    else:
        print("\nservice-model check skipped (botocore without the AgentCore models; pip install boto3)")
    print(f"credentials present: {credentials_present()} (dry run makes no calls either way)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
