"""Render a Strands JSONL trace (one span per line) as an indented text tree.

    python scripts/render_trace.py docs/traces/demo_one.jsonl docs/traces/demo_one.txt

Each line: span name, status, duration, tool name and status for tool spans, guardrail events
(hook.cancel_tool, steering.guide, steering.interrupt), and the cancel text when a tool was cancelled.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

GUARD_EVENTS = ("hook.", "steering.")


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _ms(span: dict) -> float:
    start = datetime.fromisoformat(span["start_time"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(span["end_time"].replace("Z", "+00:00"))
    return (end - start).total_seconds() * 1000


def _label(span: dict) -> str:
    attrs = span.get("attributes", {})
    status = span["status"]["status_code"]
    parts = [f"{span['name']} [{status}] {_ms(span):.1f}ms"]
    if span["name"].startswith("execute_tool"):
        parts.append(f"tool={attrs.get('gen_ai.tool.name')} tool.status={attrs.get('gen_ai.tool.status')}")
    guard = [e for e in span.get("events", []) if e["name"].startswith(GUARD_EVENTS)]
    for e in guard:
        detail = ", ".join(f"{k}={v}" for k, v in e.get("attributes", {}).items())
        parts.append(f"| {e['name']}({detail})")
    choice = next((e for e in span.get("events", []) if e["name"] == "gen_ai.choice"), None)
    if choice and span["name"].startswith("execute_tool"):
        message = choice["attributes"].get("message", "")
        if "cancelled" in message.lower():
            parts.append("<- " + message[:110].replace("\n", " "))
    return " ".join(parts)


def render(spans: list[dict]) -> str:
    children: dict[str | None, list[dict]] = {}
    for span in spans:
        children.setdefault(span.get("parent_id"), []).append(span)
    for group in children.values():
        group.sort(key=lambda s: s["start_time"])
    lines: list[str] = []

    def walk(parent: str | None, depth: int) -> None:
        for span in children.get(parent, []):
            lines.append("  " * depth + "- " + _label(span))
            walk(span["context"]["span_id"], depth + 1)

    walk(None, 0)
    guard_total = sum(1 for s in spans for e in s.get("events", []) if e["name"].startswith(GUARD_EVENTS))
    lines.append("")
    lines.append(f"{len(spans)} spans; {guard_total} guardrail event(s).")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    src = Path(argv[0])
    text = render(load(src))
    if len(argv) > 1:
        Path(argv[1]).write_text(text)
        print(f"rendered {src} -> {argv[1]}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
