"""Span events for the evidence packet.

Cancelled tool calls already surface as ERROR spans in Strands' traces. The
gates add named events on top so a trace reader can see which gate fired:

    hook.cancel_tool              KB gate cancelled a tool call
    steering.guide                option-order gate before the tool
    steering.guide_after_model    plan gate discarded a final plan
    steering.proceed_after_model  plan gate accepted the final plan
    interrupt.raised              a human decision was requested
    interrupt.resumed             the human answered and the run resumed
    interrupt.superseded          an open question closed because its rule no longer held (daytime)
    memory.degraded               an AgentCore Memory call failed; the session's copy carried on
    memory.replayed               a write that failed earlier reached Memory
    decision.cleared              the outage ended; the rider's answer for it is forgotten

`add_span_event` is a no-op without a configured tracer, so production code
never depends on tracing being on.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace as trace_api

HOOK_CANCEL = "hook.cancel_tool"
TOOL_RAN = "tool.ran"  # the draft tool executed with these arguments (recorded by the KB hook after the call)
GUIDE_BEFORE = "steering.guide"
GUIDE_AFTER = "steering.guide_after_model"
PROCEED_AFTER = "steering.proceed_after_model"
INTERRUPT_RAISED = "interrupt.raised"
INTERRUPT_RESUMED = "interrupt.resumed"
INTERRUPT_SUPERSEDED = "interrupt.superseded"
MEMORY_DEGRADED = "memory.degraded"
MEMORY_REPLAYED = "memory.replayed"
DECISION_CLEARED = "decision.cleared"

SPAN_EVENTS = (
    HOOK_CANCEL,
    GUIDE_BEFORE,
    GUIDE_AFTER,
    PROCEED_AFTER,
    INTERRUPT_RAISED,
    INTERRUPT_RESUMED,
    INTERRUPT_SUPERSEDED,
    MEMORY_DEGRADED,
    MEMORY_REPLAYED,
    DECISION_CLEARED,
)


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        if v is None:
            continue
        out[k] = v if isinstance(v, (str, bool, int, float)) else str(v)
    return out


def record_event(name: str, **attrs: Any) -> None:
    """An event that may happen outside any span (a store call before the agent runs): added to the current
    span when there is one, otherwise put on a short span of its own so the trace and the evidence keep it."""
    span = trace_api.get_current_span()
    if span.get_span_context().is_valid:
        add_span_event(name, **attrs)
        return
    try:
        with trace_api.get_tracer("le_dispatch").start_as_current_span(name.split(".")[0]):
            add_span_event(name, **attrs)
    except Exception:  # pragma: no cover - tracing must never break a run
        pass


def add_span_event(name: str, **attrs: Any) -> None:
    span = trace_api.get_current_span()
    try:
        span.add_event(name, attributes=_clean(attrs))
    except Exception:  # pragma: no cover - tracing must never break a run
        pass


_exporter = None


def memory_exporter():
    """Install (once) an in-memory exporter on the global tracer provider and
    return it. Used by tests and by `demo_one.py --trace` to render events."""
    global _exporter
    if _exporter is not None:
        return _exporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    _exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    trace_api.set_tracer_provider(provider)
    return _exporter


def collect_events(exporter) -> list[dict[str, Any]]:
    """Flatten our named events out of finished spans, oldest first."""
    found = []
    for span in exporter.get_finished_spans():
        for ev in span.events:
            if ev.name in SPAN_EVENTS:
                found.append(
                    {
                        "span": span.name,
                        "event": ev.name,
                        "attributes": dict(ev.attributes or {}),
                        "time": ev.timestamp,
                    }
                )
    found.sort(key=lambda e: e["time"])
    return found


def render_events(events: list[dict[str, Any]]) -> str:
    """One line per gate event, the shape docs/traces/ renders in the main repo."""
    lines = []
    for e in events:
        attrs = " ".join(f"{k}={v!r}" for k, v in sorted(e["attributes"].items()))
        lines.append(f"{e['event']:<30} span={e['span']} {attrs}")
    return "\n".join(lines)
