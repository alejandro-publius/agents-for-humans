"""Custom code-based evaluator: did the agent's plan carry the KB label?

Written to the AgentCore Evaluations custom code-based evaluator contract
(developer guide, code-based-evaluators). The Lambda receives

    {
      "schemaVersion": "1.0", "evaluatorId": "...", "evaluatorName": "...",
      "evaluationLevel": "TRACE" | "TOOL_CALL" | "SESSION",
      "evaluationInput": {"sessionSpans": [...]},
      "evaluationReferenceInputs": [...],      # the Evaluate API's shape: expectedResponse.text, assertions[].text,
                                              # expectedTrajectory.toolNames (the local runner may pass
                                              # {"expected_option": label} directly)
      "evaluationTarget": {"traceIds": [...], "spanIds": [...]}
    }

and returns {"label": str (required), "value": float, "explanation": str}
or {"errorCode": ..., "errorMessage": ...}. Limits: 6 MB payload, 300 s.

`evaluate(payload)` is a pure function so it is unit-tested offline on
mock traces and on real Strands spans; `lambda_handler` is the one-line
wrapper. No AWS imports.

Where the option lives in real Strands spans (read from the SDK's own
OpenTelemetry output, F11): the `execute_tool Plan` span carries a
`gen_ai.tool.message` event whose `content` attribute is the Plan JSON;
`execute_tool draft_plan` carries the draft arguments the same way; the
`invoke_agent` span's `gen_ai.choice` event carries the final structured
output. The parser reads events first, then attributes, and accepts both
mapping-style and OTLP key/value-list attributes.
"""

from __future__ import annotations

import json
import re
from typing import Any

RANKED_OPTIONS = ("alternate_elevator", "backtracking", "transit", "mitigation_trip", "mitigation_shuttle")
PLAN_TOOLS = ("Plan", "draft_plan")
NAME_KEYS = ("gen_ai.tool.name", "tool.name")
ARG_KEYS = ("gen_ai.tool.call.arguments", "tool.arguments", "input.value", "gen_ai.request.input")
OUT_KEYS = ("gen_ai.tool.call.result", "tool.result", "output.value", "gen_ai.response.output")
EVENT_CONTENT_KEYS = ("content", "message")


def _attrs(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    out: dict[str, Any] = {}
    for kv in obj:
        if isinstance(kv, dict) and "key" in kv:
            val = kv.get("value", {})
            if isinstance(val, dict):
                val = next(iter(val.values()), None)
            out[kv["key"]] = val
    return out


def _spans(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return payload.get("evaluationInput", {}).get("sessionSpans", []) or []


OPTION_IN_TEXT = re.compile(r"\boption(?: label is| is)? (" + "|".join(RANKED_OPTIONS) + r")\b")


def _option_in_text(text: Any) -> str | None:
    m = OPTION_IN_TEXT.search(text) if isinstance(text, str) else None
    return m.group(1) if m else None


def _expected_option(payload: dict[str, Any]) -> str | None:
    """The ground truth, from the Evaluate API's reference-input shape first (expectedResponse.text, the
    assertions' text: what the dataset's expected_response and assertions become), then the plain keys the
    local runner passes."""
    for ref in payload.get("evaluationReferenceInputs", []) or []:
        if not isinstance(ref, dict):
            continue
        expected = ref.get("expectedResponse")
        found = _option_in_text(expected.get("text")) if isinstance(expected, dict) else None
        if found:
            return found
        for assertion in ref.get("assertions") or []:
            found = _option_in_text(assertion.get("text") if isinstance(assertion, dict) else assertion)
            if found:
                return found
        if "expected_option" in ref:
            return ref["expected_option"]
        content = ref.get("content", ref.get("value"))
        if isinstance(content, dict) and "expected_option" in content:
            return content["expected_option"]
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict) and "expected_option" in parsed:
                return parsed["expected_option"]
    return None


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return None
        if isinstance(parsed, list):  # a message content list: find the first toolUse or JSON text
            for block in parsed:
                if isinstance(block, dict):
                    if "toolUse" in block and isinstance(block["toolUse"].get("input"), dict):
                        return block["toolUse"]["input"]
                    if "text" in block:
                        inner = _as_dict(block["text"])
                        if inner:
                            return inner
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _option_from(obj: dict[str, Any] | None) -> str | None:
    if obj and isinstance(obj.get("option"), str):
        return obj["option"]
    return None


def _tool_name(span: dict[str, Any]) -> str:
    attrs = _attrs(span.get("attributes"))
    for k in NAME_KEYS:
        if k in attrs:
            return str(attrs[k])
    name = str(span.get("name", ""))
    return name.split(" ", 1)[1] if name.startswith("execute_tool ") else name


def _chosen_option(spans: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """The option in the last plan-shaped tool call (Plan wins over draft_plan
    when both appear last), and where it was found."""
    best: tuple[int, str, str] | None = None  # (priority, option, where)
    for idx, span in enumerate(spans):
        tool = _tool_name(span)
        attrs = _attrs(span.get("attributes"))
        candidates: list[tuple[str, str | None]] = []
        if tool in PLAN_TOOLS:
            for ev in span.get("events", []) or []:
                ev_attrs = _attrs(ev.get("attributes"))
                for key in EVENT_CONTENT_KEYS:
                    if key in ev_attrs:
                        candidates.append((f"{tool}:{ev.get('name')}.{key}", _option_from(_as_dict(ev_attrs[key]))))
            for key in ARG_KEYS + OUT_KEYS:
                if key in attrs:
                    candidates.append((f"{tool}:{key}", _option_from(_as_dict(attrs[key]))))
        if tool == "invoke_agent" or str(span.get("name", "")).startswith("invoke_agent"):
            for ev in span.get("events", []) or []:
                if ev.get("name") == "gen_ai.choice":
                    ev_attrs = _attrs(ev.get("attributes"))
                    candidates.append(
                        (f"invoke_agent:{ev.get('name')}.message", _option_from(_as_dict(ev_attrs.get("message"))))
                    )
        for where, option in candidates:
            if option is None:
                continue
            priority = idx * 10 + (2 if tool == "Plan" else 1 if tool == "invoke_agent" else 0)
            if best is None or priority >= best[0]:
                best = (priority, option, where)
    return (best[1], best[2]) if best else (None, None)


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    expected = _expected_option(payload)
    if expected is None:
        return {"errorCode": "MISSING_GROUND_TRUTH", "errorMessage": "no expected_option in evaluationReferenceInputs"}
    chosen, where = _chosen_option(_spans(payload))
    if chosen is None:
        return {"label": "FAIL", "value": 0.0, "explanation": "no plan option found in the session spans"}
    if chosen == expected:
        explanation = f"agent chose {chosen!r} ({where}), matching the KB label"
        return {"label": "PASS", "value": 1.0, "explanation": explanation}
    return {"label": "FAIL", "value": 0.0, "explanation": f"agent chose {chosen!r} ({where}); KB label is {expected!r}"}


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    return evaluate(event)
