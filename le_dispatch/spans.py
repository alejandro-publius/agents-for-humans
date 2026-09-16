"""Strands OpenTelemetry spans as JSON, the shape an evaluator payload carries.

Strands puts the tool call arguments in a span EVENT (`gen_ai.tool.message`,
attribute `content` = the input JSON) on the `execute_tool <name>` span, and
the final structured output in the `gen_ai.choice` event on the
`invoke_agent` span; the tool name is the `gen_ai.tool.name` attribute.
Confirmed by reading real spans from the in-memory exporter (F11). The
custom evaluator reads both events and attributes, so a payload built from
these spans and a payload built by AgentCore from the same OTel data both
evaluate.
"""

from __future__ import annotations

from typing import Any


def span_to_json(span: Any) -> dict[str, Any]:
    """A ReadableSpan (opentelemetry-sdk) as plain JSON."""
    ctx = span.get_span_context()
    parent = span.parent
    return {
        "name": span.name,
        "traceId": format(ctx.trace_id, "032x"),
        "spanId": format(ctx.span_id, "016x"),
        "parentSpanId": format(parent.span_id, "016x") if parent else None,
        "startTimeUnixNano": span.start_time,
        "endTimeUnixNano": span.end_time,
        "attributes": {k: v for k, v in dict(span.attributes or {}).items()},
        "events": [
            {"name": ev.name, "timeUnixNano": ev.timestamp, "attributes": dict(ev.attributes or {})}
            for ev in span.events
        ],
        "status": str(getattr(span.status, "status_code", "")),
    }


def session_spans(exporter: Any) -> list[dict[str, Any]]:
    """All finished spans from an InMemorySpanExporter, oldest first."""
    spans = [span_to_json(s) for s in exporter.get_finished_spans()]
    spans.sort(key=lambda s: s["startTimeUnixNano"] or 0)
    return spans


def evaluator_payload(
    spans: list[dict[str, Any]],
    *,
    expected_option: str,
    evaluator_name: str = "LastElevatorOptionEquality",
    level: str = "TRACE",
) -> dict[str, Any]:
    """The Lambda payload shape from the code-based evaluator docs; the reference input in the Evaluate API's
    shape (an assertion naming the label, as the dataset's assertions do), so the local run exercises what
    the deployed evaluator will read."""
    trace_ids = sorted({s["traceId"] for s in spans})
    return {
        "schemaVersion": "1.0",
        "evaluatorId": "local",
        "evaluatorName": evaluator_name,
        "evaluationLevel": level,
        "evaluationInput": {"sessionSpans": spans},
        "evaluationReferenceInputs": [
            {
                "context": {"spanContext": {"sessionId": "local", "traceId": trace_ids[0] if trace_ids else ""}},
                "assertions": [{"text": f"The plan's option label is {expected_option}"}],
            }
        ],
        "evaluationTarget": {"traceIds": trace_ids, "spanIds": []},
    }
