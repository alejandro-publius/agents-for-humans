"""make video-assets: the exact command behind every on-screen moment of docs/video-script.md, run here on the
scripted model and the fixtures, with the observed output and the lines to freeze on; two renders for the cut.

Writes docs/video/commands.md (one section per moment: the time in the script, the command, the lines to
freeze on as they were printed, the whole observed output), docs/video/trace.png (the gate span events of
`make demo-one-trace`) and docs/video/eval_table.png (the policy-agreement table; the mock rows are labelled
as such and the live rows are the laptop's to regenerate). Nothing here is a result: every number on screen
is the fixture run's until the laptop reruns it, and the script says so where it matters.
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "video"
PY = sys.executable

TERMINAL_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin: 0; background: #0f172a; }}
pre {{ margin: 0; padding: 28px 32px; color: #e2e8f0; font: 15px/1.45 "SF Mono", Menlo, Consolas, monospace;
      white-space: pre; display: inline-block; min-width: 1120px; }}
.t {{ color: #7dd3fc; }} .z {{ color: #86efac; }} .r {{ color: #fca5a5; }}
table {{ border-collapse: collapse; color: #e2e8f0; font: 15px/1.5 "SF Mono", Menlo, Consolas, monospace; }}
th, td {{ border: 1px solid #334155; padding: 8px 14px; text-align: left; }} th {{ color: #7dd3fc; }}
caption {{ caption-side: top; color: #94a3b8; padding: 0 0 10px; text-align: left; }}
div.wrap {{ display: inline-block; padding: 28px 32px; }}
</style></head><body>{body}</body></html>"""


@dataclass(frozen=True)
class Moment:
    key: str
    at: str  # where it sits in docs/video-script.md
    title: str
    command: str  # what to type, as the viewer sees it
    argv: list[str]  # what runs here
    freeze: list[str]  # regexes, one per line to freeze on, in order
    note: str = ""


MOMENTS: list[Moment] = [
    Moment(
        "brief",
        "1:20 to 2:45",
        "The first shot: the whole run in plain lines (what code decided, what the model tried, what stopped it)",
        "make demo-one-brief",
        [PY, "scripts/demo_one.py", "--brief"],
        [
            r"^code decided: ",
            r"^the model tried \(1\): draft_plan with elevator='FAKE-E7'",
            r"^  what stopped it: the hook cancelled it before the tool ran$",
            r"^  what stopped it: the steering gate before the tool sent it back with BART's order$",
            r"^  what stopped it: the steering gate after the model threw the plan away$",
            r"^what reached the rider: ",
            r"^models propose, code decides$",
        ],
        "Open on this; the trace shot (below) is the same run as the SDK saw it.",
    ),
    Moment(
        "note",
        "2:45 to 3:30",
        "The rider's own words: read by the model into a fixed vocabulary, applied by code as feasibility",
        "make demo-one-brief DEMO_ONE_ARGS='--note \"No ramps today, I am pushing a stroller\"'",
        [PY, "scripts/demo_one.py", "--brief", "--note", "No ramps today, I am pushing a stroller"],
        [
            r'^the rider wrote: "No ramps today, I am pushing a stroller"; read as: no ramps \(model\)',
            r"^code decided: .* the transit connection BART lists, about 20 minutes more$",
        ],
        "The alternate elevator's route uses a ramp, so it is out for this rider today; BART's next option, with the "
        "policy engine's minutes. The note can only take options away, never add, reorder or number them.",
    ),
    Moment(
        "hook_cancel",
        "1:20 to 2:45",
        "The hook cancels a call that names an elevator the knowledge base does not have",
        "make demo-one-trace",
        [PY, "scripts/demo_one.py", "--trace"],
        [r"^hook cancels: 1$", r"^hook\.cancel_tool .*FAKE-E7"],
        "The model asked for FAKE-E7; the Strands BeforeToolCallEvent hook cancelled the call before the tool ran, "
        "and the cancel message names the right station and elevator.",
    ),
    Moment(
        "guide_before_tool",
        "1:20 to 2:45",
        "A steering Guide before the tool: BART's order puts alternate elevator first",
        "make demo-one-trace",
        [PY, "scripts/demo_one.py", "--trace"],
        [r"^guide before tool: 1$", r"^steering\.guide .*BART's published order"],
    ),
    Moment(
        "guide_after_model",
        "1:20 to 2:45",
        "A steering Guide after the model: the plan with the wrong option and invented minutes is thrown away",
        "make demo-one-trace",
        [PY, "scripts/demo_one.py", "--trace"],
        [
            r"^guide after model: 1$",
            r"^steering\.guide_after_model .*Plan rejected",
            r"^steering\.proceed_after_model .*plan\.option='alternate_elevator'",
        ],
        "The final plan line is the one to end on: the knowledge base's station, BART's option, the policy engine's "
        "minutes, the sentence composed by code.",
    ),
    Moment(
        "final_plan",
        "1:20 to 2:45",
        "The plan that reaches the rider",
        "make demo-one-trace",
        [PY, "scripts/demo_one.py", "--trace"],
        [r'^final plan: \{"station":"DELN","elevator":"DELN-E1","option":"alternate_elevator","added_minutes":4'],
    ),
    Moment(
        "red_team",
        "1:20 to 2:45",
        "The red-team counts: reached the rider, zero, zero, zero, zero",
        "make red-team",
        [PY, "scripts/red_team.py"],
        [
            r"^red team: 140 runs",
            r"^  reached rider: hallucinated_stations=0 wrong_options=0 minutes_not_from_policy=0 "
            r"unapproved_messages=0$",
            r"^  plans delivered: 140",
        ],
        'Say "fixture run" until the laptop has rerun it; the last line prints the provenance (claimable: False).',
    ),
    Moment(
        "ablation",
        "1:20 to 2:45",
        "Which gate protects what: the ablation table, one second per row",
        "make ablation",
        [PY, "scripts/ablation.py"],
        [
            r"^all_gates\s+140\s+0\s+0\s+0\s+0\s+0\b",
            r"^without_after_model_gate\s+140",
            r"^without_plan_approval\s+140",
            r"^every configuration delivered every plan: True$",
        ],
        "The rows to point at: all_gates (0 of 140 leak), without_after_model_gate (120 of 140), "
        "without_plan_approval (the injected sentences reach the rider). The same table is "
        "docs/TOUR-TRANSCRIPT.md, section 4.",
    ),
    Moment(
        "wire",
        "1:20 to 2:45 (optional, if the live shot is cut)",
        "The live path offline: the real Bedrock adapter over a stand-in client",
        "make wire",
        [PY, "scripts/bedrock_wire.py"],
        [r"^compliant ", r"^retries ", r"^access_denied ", r"^throttled ", r"^hung "],
        'Say "stand-in" on screen: this is plumbing proof, never a model result.',
    ),
    Moment(
        "interrupt",
        "2:45 to 3:30",
        "The human moment: a Strands Interrupt, the decision card, the answer, the resumed run",
        "make demo-one-after-dark",
        [PY, "scripts/demo_one.py", "--after-dark"],
        [
            r'^ "question": "It is after dark\.',
            r"^run 1 state: pending$",
            r"^rider answers: yes \(scripted\)$",
            r"^run 1 resumed state: sent$",
            r"^run 2 \(same case\) state: sent \| interrupts raised: 0$",
        ],
        "The card's question is the line a screen reader would say; run 2 shows the same case never asks twice.",
    ),
    Moment(
        "quiet_report",
        "2:45 to 3:30",
        "The weekly quiet report's opening line",
        "make report",
        [PY, "scripts/quiet_report.py"],
        [r"^7 days, 2 interruptions, 2 decisions$", r"^Interruptions per rider-week: 0\.667$"],
        "A synthetic week for three synthetic riders; the archive replay on the laptop replaces it.",
    ),
    Moment(
        "eval_table",
        "3:30 to 4:05",
        "The policy-agreement table (two models, enforced and without steering)",
        "make results-table",
        [PY, "scripts/render_results_table.py"],
        [r"^\| Provider \| Model \| Mode \|", r"^\| mock \| `mock-echo` \| enforced \|"],
        "The mock rows are plumbing proof and say so in their Status column; the live rows appear after "
        "`make eval-live` on the laptop, and eval_table.png is regenerated then (`make video-assets`).",
    ),
    Moment(
        "trace",
        "1:20 to 2:45 and 3:30 to 4:05",
        "The trace render: every gate as a span event",
        "make demo-one-trace",
        [PY, "scripts/demo_one.py", "--trace"],
        [
            r"^== gate span events ==$",
            r"^hook\.cancel_tool ",
            r"^steering\.guide ",
            r"^steering\.guide_after_model ",
            r"^steering\.proceed_after_model ",
        ],
        "trace.png is this block, rendered.",
    ),
]


def run(argv: list[str]) -> str:
    out = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=900)
    text = out.stdout + (("\n[stderr]\n" + out.stderr) if out.returncode else "")
    return text.rstrip("\n")


def freeze_lines(output: str, patterns: list[str]) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []
    for pattern in patterns:
        match = next((line for line in output.splitlines() if re.search(pattern, line)), None)
        found.append((pattern, match))
    return found


def commands_md(outputs: dict[str, str]) -> str:
    lines = [
        "# The commands behind the video (generated by make video-assets; do not edit)",
        "",
        "One section per on-screen moment of `docs/video-script.md`: the time, the command to type, the lines",
        "to freeze on exactly as they were printed here, then the whole observed output. Run on the scripted",
        "model and the fixtures in the dispatch sandbox; every number is the fixture run's until the laptop",
        "reruns it (`docs/SUNDAY.md`), and the live-model shot is never simulated.",
        "",
    ]
    for m in MOMENTS:
        output = outputs[m.key]
        lines += [f"## {m.title}", "", f"At {m.at} in the script. Command:", "", "```", f"$ {m.command}", "```", ""]
        if m.note:
            lines += [m.note, ""]
        lines += ["Freeze on:", "", "```"]
        for pattern, match in freeze_lines(output, m.freeze):
            lines.append(match if match is not None else f"[not printed: /{pattern}/]")
        lines += [
            "```",
            "",
            "Observed output:",
            "",
            "```",
            output if len(output) < 6000 else output[:6000] + "\n[...]",
            "```",
            "",
        ]
    return "\n".join(lines)


def check(outputs: dict[str, str]) -> list[str]:
    problems = []
    for m in MOMENTS:
        for pattern, match in freeze_lines(outputs[m.key], m.freeze):
            if match is None:
                problems.append(f"{m.key}: no line matches /{pattern}/")
    return problems


def render_pngs(outputs: dict[str, str]) -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("video-assets: playwright not installed; PNGs skipped")
        return []
    trace = outputs["trace"]
    block = trace[trace.index("== gate span events ==") :]
    wrapped = []  # the reasons are long: wrapped for the frame, with the event name kept as the first column
    for line in block.splitlines():
        wrapped.extend(textwrap.wrap(line, width=116, subsequent_indent=" " * 31, break_long_words=False) or [""])
    text = html.escape("\n".join(wrapped))
    text = re.sub(r"^(== .*==)$", r'<span class="t">\1</span>', text, flags=re.M)
    text = re.sub(
        r"^(hook\.cancel_tool|steering\.guide|steering\.guide_after_model)(\s)",
        r'<span class="r">\1</span>\2',
        text,
        flags=re.M,
    )
    text = re.sub(r"^(steering\.proceed_after_model)(\s)", r'<span class="z">\1</span>\2', text, flags=re.M)
    trace_html = TERMINAL_HTML.format(body=f"<pre>{text}</pre>")
    table_md = outputs["eval_table"]
    rows = [line for line in table_md.splitlines() if line.startswith("|")]
    cells = [[c.strip() for c in row.strip("|").split("|")] for row in rows if not set(row) <= set("|- ")]
    head, body = cells[0], cells[1:]
    table = (
        "<table><caption>Policy agreement (make results-table): mock rows are plumbing proof; live rows come "
        "from make eval-live on the laptop</caption>"
    )
    table += "<tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in head) + "</tr>"
    for row in body:
        table += "<tr>" + "".join(f"<td>{html.escape(c.replace('`', ''))}</td>" for c in row) + "</tr>"
    table += "</table>"
    table_html = TERMINAL_HTML.format(body=f'<div class="wrap">{table}</div>')
    written = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(device_scale_factor=2)
        for name, content, selector in (("trace.png", trace_html, "pre"), ("eval_table.png", table_html, "div.wrap")):
            page.set_content(content)
            target = OUT / name
            page.locator(selector).screenshot(path=str(target))
            written.append(target)
        browser.close()
    return written


def storyboard_md(outputs: dict[str, str]) -> str:
    """One page for the cut: the script's sections in order, each with its voice lines and the moments that
    sit in it (the command as the viewer sees it, the first line to freeze on as it was printed). Built
    from docs/video-script.md and MOMENTS, so it cannot drift from either."""
    script = (ROOT / "docs" / "video-script.md").read_text()
    sections = re.split(r"(?m)^## (?=\d)", script)[1:]  # "0:00 to 0:10, headline ..." blocks
    lines = [
        "# Storyboard (generated by make video-assets; do not edit)",
        "",
        "The script's sections in order, each with its voice lines (one breath each) and the screen moments",
        "that sit in it: the command as the viewer sees it and the first line to freeze on, as it printed here.",
        "`docs/video/commands.md` has every freeze line and the whole output; `docs/video-script.md` the shots.",
        "",
    ]
    for block in sections:
        heading, _, body = block.partition("\n")
        when = heading.split(",", 1)[0].strip()
        lines += [f"## {heading.strip()}", ""]
        vo = [ln[3:].strip() for ln in body.splitlines() if ln.startswith("VO:")]
        if vo:
            lines += ["Voice:", ""] + [f"- {v}" for v in vo] + [""]
        moments = [m for m in MOMENTS if when in m.at]  # "1:20 to 2:45 (optional ...)" sits in 1:20 to 2:45
        if moments:
            lines += ["| Screen | Command | Freeze on |", "|---|---|---|"]
            for m in moments:
                frozen = freeze_lines(outputs.get(m.key, ""), m.freeze)
                first = next((text for _, text in frozen if text), "")
                lines.append(f"| {m.title} | `{m.command}` | `{first.replace('|', '/')}` |")
            lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    cache: dict[tuple[str, ...], str] = {}
    for m in MOMENTS:
        key = tuple(m.argv)
        if key not in cache:
            cache[key] = run(m.argv)
        outputs[m.key] = cache[key]
    problems = check(outputs)
    (OUT / "commands.md").write_text(commands_md(outputs))
    (OUT / "storyboard.md").write_text(storyboard_md(outputs))
    written = render_pngs(outputs)
    print(f"wrote {OUT / 'commands.md'} ({len(MOMENTS)} moments) and {OUT / 'storyboard.md'}")
    for path in written:
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    for p in problems:
        print(f"MISSING {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
