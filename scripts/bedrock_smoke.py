"""One Converse call to the model the eval will use, in AWS_REGION. Prints the reply and token usage.

    make bedrock-smoke      # needs ~/.aws credentials or AWS_* variables; AWS_REGION defaults to us-west-2

Model: EVAL_MODEL_ID if set, else the Strands default Bedrock model id (a Claude Sonnet inference
profile). No other AWS call is made and nothing is created.
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from strands.models.bedrock import DEFAULT_BEDROCK_MODEL_ID


def main() -> int:
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"
    model_id = os.getenv("EVAL_MODEL_ID") or DEFAULT_BEDROCK_MODEL_ID
    try:
        client = boto3.client("bedrock-runtime", region_name=region)
        resp = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "Reply with exactly one word: ready"}]}],
            inferenceConfig={"maxTokens": 20, "temperature": 0},
        )
    except NoCredentialsError:
        print("bedrock-smoke: no AWS credentials found", file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError) as exc:
        print(f"bedrock-smoke: FAILED for {model_id} in {region}: {exc}", file=sys.stderr)
        return 1
    text = " ".join(c.get("text", "") for c in resp["output"]["message"]["content"])
    usage = resp.get("usage", {})
    print(f"bedrock-smoke: model={model_id} region={region} reply={text!r} usage={usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
