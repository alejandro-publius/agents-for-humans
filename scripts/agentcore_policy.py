"""make agentcore-policy: print the plan (--dry-run, default) or apply it (laptop only).

python scripts/agentcore_policy.py --dry-run
python scripts/agentcore_policy.py --apply --yes --gateway-role-arn arn:... --mcp-endpoint https://...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.agentcore_policy import (  # noqa: E402
    DEFAULT_REGION,
    api_calls,
    apply,
    credentials_present,
    plan,
)
from le_dispatch.api_shapes import check_calls, service_models_available  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print every resource and permission; default")
    mode.add_argument("--apply", action="store_true", help="make the boto3 calls (needs credentials and --yes)")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--region", default=DEFAULT_REGION)
    ap.add_argument("--gateway-id", default=None, help="attach to an existing gateway instead of creating one")
    ap.add_argument("--gateway-role-arn", default="${GATEWAY_ROLE_ARN}")
    ap.add_argument("--mcp-endpoint", default=None, help="URL of the E7 MCP server")
    args = ap.parse_args(argv)

    p = plan(
        region=args.region,
        gateway_id=args.gateway_id,
        gateway_role_arn=args.gateway_role_arn,
        mcp_endpoint=args.mcp_endpoint,
    )
    if args.apply:
        if not credentials_present():
            print("no AWS credentials in the environment; printing the plan instead")
            print(p.render())
            return 2
        created = apply(p, yes=args.yes, region=args.region)
        print(json.dumps(created, indent=2))
        return 0
    print(p.render())
    if service_models_available():
        problems = check_calls(api_calls(p))
        if problems:
            print("\nservice-model check FAILED (botocore would reject these calls):")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print(f"\nservice-model check: every call above is well formed ({len(p.steps)} operations, botocore)")
    else:
        print("\nservice-model check skipped (botocore without the AgentCore models; pip install boto3)")
    print(f"credentials present: {credentials_present()} (dry run makes no calls either way)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
