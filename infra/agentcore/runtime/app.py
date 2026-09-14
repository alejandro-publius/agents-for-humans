"""The file `agentcore configure -e infra/agentcore/runtime/app.py` points at.

The starter toolkit wants a module-level `app` (a BedrockAgentCoreApp with an `@app.entrypoint`); the
dispatch entrypoint keeps its app lazy so it stays importable and testable without the SDK. This file is
the thin layer between the two: it builds the app once, from the environment, and runs it as the
container's command.

    LAST_ELEVATOR_MODEL_ID   the Bedrock model or inference profile id (default: Nova Lite); "stand-in" serves
                             the same app on the learner stand-in through the real Bedrock adapter, no key,
                             no call (make serve: a judge can curl the contract on a laptop)
    AWS_REGION               the region (default: us-west-2)
    LAST_ELEVATOR_DATA       inbox, sent log and decision mirrors (default: /tmp/last-elevator)
    LAST_ELEVATOR_MEMORY_ID  the AgentCore Memory for the durable copies; "stand-in" keeps them in memory
    OTEL_EXPORTER_OTLP_ENDPOINT   set by the runtime's observability setup; the gate events go to CloudWatch
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the toolkit copies this directory into the image
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # le_dispatch, when run from the repo

from entrypoint import bedrock_model_factory, decision_store_factory, make_runtime  # noqa: E402

MODEL_ID = os.environ.get("LAST_ELEVATOR_MODEL_ID", "us.amazon.nova-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-west-2")
STAND_IN = "stand-in"


def stand_in_model_factory():
    """The learner stand-in through the real Bedrock adapter: the same app, nothing called."""
    from le_dispatch.bedrock_wire import wired_learner_model

    def make(trip, decision):
        return wired_learner_model("us.amazon.nova-lite-v1:0", REGION)

    return make


def stand_in_stores():
    """One in-memory Memory stand-in for the process, every call validated against the service model."""
    from le_dispatch.agentcore_memory import FakeMemoryClient

    return decision_store_factory("mem-stand-in-0123456789", REGION, client=FakeMemoryClient())


def build_app():
    kwargs = {}
    if os.environ.get("LAST_ELEVATOR_DATA"):  # read when the app is built, so a serve or a test picks its own
        kwargs["data_dir"] = Path(os.environ["LAST_ELEVATOR_DATA"])
    if os.environ.get("LAST_ELEVATOR_MEMORY_ID") == STAND_IN:
        kwargs["decision_store_factory"] = stand_in_stores()
    factory = stand_in_model_factory() if MODEL_ID == STAND_IN else bedrock_model_factory(MODEL_ID, REGION)
    return make_runtime(factory, **kwargs)


app = build_app()

if __name__ == "__main__":
    app.run()
