"""Print the Amazon Bedrock AgentCore quotas for this account and region. Read-only; no resources.

    make quota            # needs AWS credentials and AWS_REGION (or AWS_DEFAULT_REGION)

Uses the Service Quotas API (boto3 ``service-quotas``). Lists every quota for the AgentCore service
code, highlighting the Runtime ones, plus the default values, so a zero applied quota is visible.
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, NoRegionError

SERVICE_CODES = ("bedrock-agentcore", "bedrock-agentcore-runtime")


def main() -> int:
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region:
        print("quota: AWS_REGION is not set", file=sys.stderr)
        return 2
    try:
        sts = boto3.client("sts", region_name=region)
        ident = sts.get_caller_identity()
        print(f"account {ident['Account']} region {region}")
        sq = boto3.client("service-quotas", region_name=region)
        found = 0
        for code in SERVICE_CODES:
            try:
                pages = sq.get_paginator("list_service_quotas").paginate(ServiceCode=code)
                quotas = [q for page in pages for q in page["Quotas"]]
            except ClientError as exc:
                print(f"{code}: {exc.response['Error']['Code']}")
                continue
            defaults = {}
            try:
                dpages = sq.get_paginator("list_aws_default_service_quotas").paginate(ServiceCode=code)
                defaults = {q["QuotaCode"]: q["Value"] for page in dpages for q in page["Quotas"]}
            except ClientError:
                pass
            for q in sorted(quotas, key=lambda q: q["QuotaName"]):
                mark = "*" if "runtime" in q["QuotaName"].lower() else " "
                default = defaults.get(q["QuotaCode"])
                line = f"{mark} {code} | {q['QuotaName']} | applied={q['Value']} default={default}"
                print(f"{line} | {q['QuotaCode']}")
                found += 1
        if not found:
            print("no quotas returned for the AgentCore service codes; check the region supports AgentCore")
            return 1
        print("* = Runtime quota. Nothing was created or changed.")
        return 0
    except NoCredentialsError:
        print("quota: no AWS credentials found", file=sys.stderr)
        return 2
    except NoRegionError:
        print("quota: no region configured", file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError) as exc:
        print(f"quota: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
