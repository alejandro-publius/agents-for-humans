"""make agentcore-deploy: the runtime deployment plan (dry run; the laptop runs the toolkit).

The AgentCore starter toolkit deploys an entrypoint in a few commands:

    agentcore configure -e infra/agentcore/runtime/app.py -n last-elevator --region us-west-2
    agentcore launch
    agentcore invoke '{"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}'

This script prints those steps, the payload contract, the environment the
entrypoint reads, and the IAM permissions. It makes no calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.interfaces import runtime_session_id  # noqa: E402

IAM = [
    "bedrock-agentcore:CreateAgentRuntime, UpdateAgentRuntime, GetAgentRuntime, InvokeAgentRuntime",
    "bedrock:InvokeModel and bedrock:InvokeModelWithResponseStream on the model or inference profile (runtime role)",
    "ecr:* on the runtime's image repository (toolkit build), iam:PassRole for the runtime role",
    "logs:CreateLogGroup, logs:PutLogEvents (runtime role); xray or OTLP export for traces",
]

SAMPLE_IN = {
    "rider_id": "r1",
    "origin": "DELN",
    "destination": "EMBR",
    "outages": ["DELN-E1"],
    "via": [],
    "after_dark": True,
    "last_train": False,
    "answer": None,
}


def main() -> int:
    print("AgentCore Runtime plan; nothing below has been executed\n")
    print(
        "1. agentcore configure -e infra/agentcore/runtime/app.py -r infra/agentcore/runtime/requirements.txt "
        "-n last-elevator --region us-west-2   (run from the repo root, so the image carries le_dispatch/)"
    )
    print(
        "2. agentcore launch            (builds the image, creates the runtime; prints the runtime ARN for the README)"
    )
    print("3. agentcore invoke '" + json.dumps(SAMPLE_IN) + "'")
    print('   expect: state pending, a decision card; then the same payload with "answer": true resumes: state sent')
    print(
        f"   invoke both with the same session id (--session-id {runtime_session_id('r1')}: "
        "runtime_session_id(rider_id) from le_dispatch.interfaces, at least 33 characters as the API requires), "
        "so the pause and the answer land on the same runtime session; an idle session is reclaimed (15 minutes "
        "at the time of writing), so poll more often than that while a question is open"
    )
    print(
        "\nenvironment read by the entrypoint: LAST_ELEVATOR_MODEL_ID, AWS_REGION, "
        "LAST_ELEVATOR_DATA (inbox, sent log and memory, the session's copies); LAST_ELEVATOR_MEMORY_ID (the "
        "AgentCore Memory that holds the durable copies: make agentcore-memory); OTEL_EXPORTER_OTLP_ENDPOINT "
        "from the runtime's observability setup (the gate events then reach CloudWatch)"
    )
    print(
        "session manager: pass session_manager_factory to make_runtime so a pause survives invocations "
        "(S3SessionManager or the main repo's)"
    )
    print("\nIAM permissions needed:")
    for p in IAM:
        print(f"  - {p}")
    print(
        "\npayload contract: see infra/agentcore/runtime/entrypoint.py docstring; "
        "tested offline in tests/test_runtime.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
