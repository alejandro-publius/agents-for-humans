"""OpenTelemetry tracing for the agent: a JSONL file exporter for offline captures, and a one-line
switch to Amazon Bedrock AgentCore Observability after deploy.

    from agent.tracing import setup_file_tracing
    setup_file_tracing("docs/traces/demo_one.jsonl")     # every Strands span, one JSON object per line

    AGENTCORE_OBSERVABILITY=1 python ...                  # OTLP exporter instead (after deploy); AgentCore
                                                          # Observability reads OTEL_EXPORTER_OTLP_ENDPOINT
                                                          # and the AgentCore-provided headers

The exporter is Strands' own ConsoleSpanExporter with a file handle and a JSON formatter, so the
file holds exactly what Strands emits (invoke_agent, execute_event_loop_cycle, chat, execute_tool
spans with gen_ai.* attributes and events). The hook and the steering handler add their own span
events (hook.cancel_tool, steering.guide, steering.interrupt) so guardrail decisions are visible.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import Any

from opentelemetry import trace as otel
from strands.telemetry import StrandsTelemetry

_telemetry: StrandsTelemetry | None = None


def span_event(name: str, attributes: dict[str, Any]) -> None:
    """Record a guardrail decision on the current span (a no-op when tracing is off)."""
    span = otel.get_current_span()
    if span is not None and span.is_recording():
        span.add_event(name, {k: str(v) for k, v in attributes.items()})


def setup_file_tracing(path: str | Path) -> StrandsTelemetry:
    """Export every span as one JSON line to ``path``. Call once per process, before the agent runs."""
    global _telemetry
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    atexit.register(handle.close)
    _telemetry = _telemetry or StrandsTelemetry()
    _telemetry.setup_console_exporter(out=handle, formatter=lambda span: span.to_json(indent=None) + "\n")
    return _telemetry


def setup_tracing_from_env() -> StrandsTelemetry | None:
    """One-line switch: AGENTCORE_OBSERVABILITY=1 sends spans over OTLP (AgentCore Observability)."""
    global _telemetry
    if os.getenv("AGENTCORE_OBSERVABILITY") == "1":
        _telemetry = _telemetry or StrandsTelemetry()
        _telemetry.setup_otlp_exporter()
        return _telemetry
    if os.getenv("TRACE_FILE"):
        return setup_file_tracing(os.environ["TRACE_FILE"])
    return None
