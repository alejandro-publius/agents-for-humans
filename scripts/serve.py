"""make serve: the AgentCore Runtime app on this machine, on the learner stand-in, no key, no call.

    python scripts/serve.py            # http://127.0.0.1:8080: the /ping and /invocations the deployed runtime serves
    PORT=8090 python scripts/serve.py

What to send is printed first. The model is the learner stand-in through Strands' real Bedrock adapter and
the durable copies are an in-memory AgentCore Memory stand-in (every call validated against the service
model), so a judge without an AWS account can drive the whole state machine with curl; the deployed runtime
answers the same payloads with a live model.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXAMPLES = [
    (
        "a daytime outage on the saved trip (sent)",
        {"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]},
    ),
    (
        "the next poll (already_sent)",
        {"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]},
    ),
    ("the elevator is back (quiet)", {"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": []}),
    (
        "after dark (pending, a decision card)",
        {"rider_id": "r2", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"], "after_dark": True},
    ),
    (
        "the rider says yes (sent)",
        {
            "rider_id": "r2",
            "origin": "DELN",
            "destination": "EMBR",
            "outages": ["DELN-E1"],
            "after_dark": True,
            "answer": True,
        },
    ),
    (
        "a note in the rider's own words (sent; the response's note field says what it ruled out and who read it)",
        {
            "rider_id": "r3",
            "origin": "DELN",
            "destination": "EMBR",
            "outages": ["DELN-E1"],
            "note": "no ramps today, I am pushing a stroller",
        },
    ),
]


def curl_lines(port: int) -> list[str]:
    lines = [f"curl -s http://127.0.0.1:{port}/ping"]
    for what, payload in EXAMPLES:
        lines.append(f"# {what}")
        lines.append(
            f"curl -s -X POST http://127.0.0.1:{port}/invocations -H 'Content-Type: application/json' "
            f"-d '{json.dumps(payload)}'"
        )
    return lines


def main(argv=None) -> int:
    os.environ.setdefault("LAST_ELEVATOR_MODEL_ID", "stand-in")
    os.environ.setdefault("LAST_ELEVATOR_MEMORY_ID", "stand-in")
    os.environ.setdefault("LAST_ELEVATOR_DATA", str(ROOT / "build" / "serve-data"))
    port = int(os.environ.get("PORT", "8080"))
    try:
        import bedrock_agentcore  # noqa: F401
    except ImportError:
        print("serve: the bedrock-agentcore SDK is not installed; pip install -e '.[aws]'")
        return 2
    sys.path.insert(0, str(ROOT / "infra" / "agentcore" / "runtime"))
    import app as runtime_app  # noqa: E402

    print("the AgentCore Runtime app, on this machine, on the learner stand-in: no key, no call\n")
    print("\n".join(curl_lines(port)))
    print()
    runtime_app.app.run(port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
