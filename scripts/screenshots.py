"""make screenshots: the numbered screenshots for the submission that need no laptop, under docs/screenshots/.

    01-decision-card.png     the decision card of `make demo-one-after-dark`, rendered the way the app shows it
    02-quiet-report.png      `make report`, the weekly quiet report (a synthetic week)
    03-trace.png             the gate span events of `make demo-one-trace` (docs/video/trace.png)
    04-eval-table.png        the policy-agreement table (docs/video/eval_table.png; mock rows labelled)
    05-red-team.png          `make red-team`, the counts
    06-architecture.png      docs/diagrams/architecture-poll.png (make diagrams)
    07-claims-badge.png      the claims badge, rendered from results/badges/claims.json
    08-axe.png               NOT generated here: the rider app's axe audit lives in the main repo (the laptop)
    09-dataset-header.png    the AgentCore Evaluations dataset: its statistics and the first scenario

Every image is labelled with what it is and whether it is a fixture run. docs/screenshots/README.md is the
index the devpost text refers to by number. Nothing here is a result until the laptop reruns it.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
PY = sys.executable

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin: 0; background: #0f172a; font: 15px/1.45 "SF Mono", Menlo, Consolas, monospace; color: #e2e8f0; }}
.wrap {{ display: inline-block; padding: 28px 32px; min-width: 900px; }}
pre {{ margin: 0; white-space: pre; }}
.t {{ color: #7dd3fc; }} .z {{ color: #86efac; }} .r {{ color: #fca5a5; }} .m {{ color: #94a3b8; }}
.label {{ color: #94a3b8; font-size: 13px; margin-bottom: 14px; }}
.card {{ background: #f8fafc; color: #0f172a; border-radius: 14px; padding: 22px 26px; max-width: 560px;
        font: 16px/1.5 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
.card h2 {{ margin: 0 0 6px; font-size: 20px; }} .card .q {{ font-size: 18px; margin: 10px 0 14px; }}
.card .row {{ display: flex; justify-content: space-between; border-top: 1px solid #e2e8f0; padding: 8px 0; }}
.card .k {{ color: #475569; }} .card .rej {{ color: #475569; font-size: 14px; margin-top: 8px; }}
.card .btns {{ display: flex; gap: 12px; margin-top: 16px; }}
.card .btn {{ flex: 1; text-align: center; padding: 12px; border-radius: 10px; font-weight: 600; }}
.yes {{ background: #16a34a; color: white; }} .no {{ background: #e2e8f0; color: #0f172a; }}
.badge {{ display: inline-flex; font: 600 22px/1 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
         border-radius: 6px; overflow: hidden; }}
.badge span {{ padding: 10px 14px; }} .badge .l {{ background: #555; color: #fff; }}
.badge .v {{ background: #1a7f37; color: #fff; }}
</style></head><body><div class="wrap">{body}</div></body></html>"""


def run(argv: list[str]) -> str:
    out = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=900)
    return out.stdout.rstrip("\n")


def terminal(label: str, text: str, width: int = 118) -> str:
    wrapped = []
    for line in text.splitlines():
        wrapped.extend(textwrap.wrap(line, width=width, subsequent_indent="    ", break_long_words=False) or [""])
    body = html.escape("\n".join(wrapped))
    body = re.sub(
        r"(reached rider: [^\n]*|zero leaks: [^\n]*|plans delivered: [^\n]*)", r'<span class="z">\1</span>', body
    )
    body = re.sub(r"^(\$ .*)$", r'<span class="t">\1</span>', body, flags=re.M)
    return f'<div class="label">{html.escape(label)}</div><pre>{body}</pre>'


def card_html(card: dict) -> str:
    rejected = "".join(
        f'<div class="rej">Not this time: {html.escape(r["label"].replace("_", " "))}. {html.escape(r["reason"])}</div>'
        for r in card.get("rejected", [])
    )
    flags = ", ".join(k.replace("_", " ") for k, v in card.get("flags", {}).items() if v)
    return (
        '<div class="label">The decision card (make demo-one-after-dark), rendered the way the rider app shows it; '
        "fixture run, the app's own screen is the laptop's</div>"
        f'<div class="card"><h2>Last Elevator needs your decision</h2>'
        f'<div class="q">{html.escape(card["question"])}</div>'
        f'<div class="row"><span class="k">BART\'s option</span>'
        f"<span>{html.escape(card['option'].replace('_', ' '))}</span></div>"
        f'<div class="row"><span class="k">Added minutes (policy engine)</span>'
        f"<span>{card['added_minutes']}</span></div>"
        f'<div class="row"><span class="k">Why now</span><span>{html.escape(flags) or "a rider decision"}</span></div>'
        f'<div class="row"><span class="k">Source</span><span>{html.escape(card["source_url"])}</span></div>'
        f"{rejected}"
        '<div class="btns"><div class="btn yes">Send this plan</div><div class="btn no">Not now</div></div></div>'
    )


def badge_html(badge: dict) -> str:
    return (
        '<div class="label">The claims badge (make badge): every number in the README is a claim CI checks '
        "against results/</div>"
        f'<div class="badge"><span class="l">{html.escape(badge["label"])}</span>'
        f'<span class="v">{html.escape(badge["message"])}</span></div>'
    )


def dataset_text() -> str:
    stats = json.loads((ROOT / "results" / "agentcore_dataset.json").read_text())
    dataset = json.loads((ROOT / "evals" / "agentcore" / "dataset.json").read_text())
    first = dataset["scenarios"][0]
    head = {k: v for k, v in stats.items() if k not in ("scenarios", "provenance")}
    return (
        f"$ make agentcore-eval-local   # the AgentCore Evaluations dataset, {len(dataset['scenarios'])} scenarios "
        f"({stats['provenance']['kb_frozen_tag']})\n"
        + json.dumps(head, indent=1)
        + "\n\nscenario 1 of "
        + str(len(dataset["scenarios"]))
        + ":\n"
        + json.dumps(first, indent=1)[:1400]
    )


def main(argv=None) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("screenshots: playwright not installed; skipped")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    after_dark = run([PY, "scripts/demo_one.py", "--after-dark"])
    card = json.loads(
        after_dark[after_dark.index("decision card: ") + len("decision card: ") :].split("\n}\n")[0] + "\n}"
    )
    report = run([PY, "scripts/quiet_report.py"])
    red = run([PY, "scripts/red_team.py"])
    badge = json.loads((ROOT / "results" / "badges" / "claims.json").read_text())
    pages = {
        "01-decision-card.png": (card_html(card), "div.wrap"),
        "02-quiet-report.png": (
            terminal(
                "$ make report   # a synthetic week for three synthetic riders; the archive replay replaces it", report
            ),
            "div.wrap",
        ),
        "05-red-team.png": (
            terminal("$ make red-team   # fixture run until the laptop reruns it on the real knowledge base", red),
            "div.wrap",
        ),
        "07-claims-badge.png": (badge_html(badge), "div.wrap"),
        "09-dataset-header.png": (terminal("", dataset_text()), "div.wrap"),
    }
    written: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(device_scale_factor=2)
        for name, (body, selector) in pages.items():
            page.set_content(PAGE.format(body=body))
            target = OUT / name
            page.locator(selector).screenshot(path=str(target))
            written.append(target)
        browser.close()
    copies = {
        "03-trace.png": ROOT / "docs" / "video" / "trace.png",
        "04-eval-table.png": ROOT / "docs" / "video" / "eval_table.png",
        "06-architecture.png": ROOT / "docs" / "diagrams" / "architecture-poll.png",
    }
    for name, source in copies.items():
        if source.exists():
            shutil.copy(source, OUT / name)
            written.append(OUT / name)
        else:
            print(
                f"screenshots: {source.relative_to(ROOT)} missing (make video-assets / make diagrams); {name} skipped"
            )
    (OUT / "README.md").write_text(index_md())
    for path in sorted(written):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    print(f"wrote {OUT.relative_to(ROOT) / 'README.md'}")
    return 0


ROWS = [
    (
        "00",
        "00-first-shot.gif",
        "the first shot: one run in plain lines, arriving one per frame (`00-first-shot.png` is the last frame)",
        "`make first-shot` (`make demo-one-brief`)",
        "unchanged (the scripted run)",
    ),
    (
        "01",
        "01-decision-card.png",
        "the decision card, rendered the way the app shows it",
        "`make demo-one-after-dark`",
        "the laptop, from the app's own screen",
    ),
    (
        "02",
        "02-quiet-report.png",
        "the weekly quiet report, opening line first",
        "`make report`",
        "the laptop, on the archive replay",
    ),
    ("03", "03-trace.png", "every gate as a span event", "`make demo-one-trace` (docs/video/trace.png)", "unchanged"),
    (
        "04",
        "04-eval-table.png",
        "the policy-agreement table, mock rows labelled",
        "`make results-table` (docs/video/eval_table.png)",
        "the laptop, after `make eval-live`",
    ),
    ("05", "05-red-team.png", "the red-team counts", "`make red-team`", "the laptop, on the real knowledge base"),
    ("06", "06-architecture.png", "one poll for one rider", "`make diagrams`", "unchanged"),
    ("07", "07-claims-badge.png", "the claims badge", "`make badge`", "the laptop, after the reruns"),
    (
        "08",
        "08-axe.png",
        "the rider app's axe audit",
        "the main repo's accessibility target",
        "the laptop only; not generated here",
    ),
    (
        "09",
        "09-dataset-header.png",
        "the AgentCore Evaluations dataset: statistics and the first scenario",
        "`make agentcore-eval-local`",
        "the laptop, on the `kb-labels-v1` export",
    ),
]


def index_md() -> str:
    lines = [
        "# Screenshots for the submission (generated by make screenshots; do not edit)",
        "",
        "Numbered the way `docs/devpost.md` refers to them. Every image says on its face whether it is a fixture",
        "run; the laptop regenerates the live ones after the Sunday runs (`make video-assets screenshots`).",
        "",
        "| # | File | What | Source | Regenerated by |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {n} | `{f}` | {what} | {source} | {by} |" for n, f, what, source, by in ROWS]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
