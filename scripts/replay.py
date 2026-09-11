"""Offline replay: run every eval case through the agent on the mock provider and write a
human-readable transcript to ``results/replay.md``. No keys, no network.

This is the judge's 60-second route (see JUDGING.md). Block B replaces the case source with the
archived BART outage feed so the same file shows real outages flowing to real plans.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from agent.mock_model import MockModel  # noqa: E402
from agent.outage_parser import parse_and_validate  # noqa: E402
from evals.run import extract_output, install_network_guard, load_suites, run_case  # noqa: E402

OUT = REPO_ROOT / "results" / "replay.md"


def _text(blocks: list[dict]) -> str:
    return " ".join(b["text"] for b in blocks if "text" in b)


def render_parse_case(suite: dict, case: dict) -> tuple[str, bool]:
    """outage_parse cases: the model proposes a parse (scripted), code validates against the KB."""
    fragment = case["input"]["fragment"]
    model = MockModel(case["input"]["mock_turns"], name=case["name"])
    validated = parse_and_validate(fragment, model)
    actual = validated.as_label()
    ok = actual == case["label"]
    lines = [f"### {suite['suite']} / {case['name']}  {'PASS' if ok else 'FAIL'}", ""]
    lines.append(f"- Fragment: `{fragment}` ({case['input'].get('source', 'authored')})")
    lines.append(
        f"- Model proposal (mock provider, scripted): `{json.dumps(case['input']['mock_turns'][0]['input'])}`"
    )
    lines.append(f"- Code validation: `{json.dumps(actual)}`")
    if validated.problems:
        lines.append(f"- Problems recorded by code: {validated.problems}")
    lines.append(f"- Expected: `{json.dumps(case['label'])}`")
    lines.append("")
    return "\n".join(lines), ok


def render_case(suite: dict, case: dict) -> tuple[str, bool]:
    if suite["output_of"] == "outage_parse":
        return render_parse_case(suite, case)
    built, result = run_case(case["input"], provider="mock", ablate=False)
    actual = extract_output(suite["output_of"], built, result)
    ok = actual == case["label"]
    lines = [f"### {suite['suite']} / {case['name']}  {'PASS' if ok else 'FAIL'}", ""]
    lines.append(f"- Prompt: `{case['input']['prompt']}`")
    lines.append(f"- Model script: `fixtures/model/{case['input']['model_fixture']}.json` (mock provider)")
    lines.append(f"- Expected `{suite['output_of']}`: `{case['label']}`  Observed: `{actual}`")
    lines.append("")
    lines.append("Conversation:")
    for message in built.agent.messages:
        role = message["role"]
        for block in message.get("content", []):
            if "text" in block:
                lines.append(f"- **{role}**: {block['text'].strip()}")
            elif "toolUse" in block:
                tu = block["toolUse"]
                lines.append(f"- **{role} -> tool** `{tu['name']}` {json.dumps(tu['input'])}")
            elif "toolResult" in block:
                tr = block["toolResult"]
                text = _text(tr.get("content", []))
                tag = "CANCELLED" if "CANCELLED" in text else tr["status"]
                lines.append(f"- **tool result** [{tag}] {text[:200]}")
    if built.steering and built.steering.rewrites:
        for rw in built.steering.rewrites:
            lines.append(f"- **steering rewrote the response**: {rw['reason']}")
    plan = getattr(result, "structured_output", None)
    if plan is not None:
        lines.append(f"- **Plan**: `{plan.model_dump_json()}`")
    lines.append("")
    return "\n".join(lines), ok


def main() -> int:
    install_network_guard()
    start = time.perf_counter()
    suites = load_suites()
    parts = [
        "# Replay (offline, mock provider)",
        "",
        "Every eval case run through the real Strands agent loop with a scripted model. Tool calls, hook",
        "cancellations, steering rewrites, and the final structured Plan are shown as they happened.",
        "Nothing here touched the network. Regenerate with `make replay`.",
        "",
    ]
    total = passed = 0
    for suite in suites:
        parts.append(f"## Suite `{suite['suite']}`")
        parts.append("")
        parts.append(suite["description"])
        parts.append("")
        for case in suite["cases"]:
            text, ok = render_case(suite, case)
            parts.append(text)
            total += 1
            passed += ok
    elapsed = time.perf_counter() - start
    parts.append(f"---\n{passed}/{total} cases matched their label.\n")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(parts))
    print(f"replay: {passed}/{total} cases, wrote {OUT.relative_to(REPO_ROOT)} in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
