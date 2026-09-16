"""make diagrams: the pictures for the Devpost gallery and the video, under docs/diagrams/.

- the two Mermaid blocks of docs/ARCHITECTURE.md as SVG and PNG
- the sequence diagram of each evidence packet in docs/evidence/ as PNG
- the tour transcript's seven sections as terminal-styled PNGs (Playwright's Chromium)

Needs the mermaid CLI (`npm i -g @mermaid-js/mermaid-cli`) and a Chromium; each part is skipped with a
note when its tool is absent. GitHub renders the Markdown blocks itself; the files are for the gallery.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "ARCHITECTURE.md"
OUT = ROOT / "docs" / "diagrams"
NAMES = ["architecture-poll", "human-moment"]
CHROMIUM_CANDIDATES = [
    os.environ.get("PUPPETEER_EXECUTABLE_PATH", ""),
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
]


def _render_mermaid(mmdc: str, cfg: Path, tmp: Path, name: str, block: str, formats: tuple[str, ...]) -> bool:
    src = tmp / f"{name}.mmd"
    src.write_text(block)
    for ext in formats:
        extra = ["-w", "1600", "-b", "white"] if ext == "png" else []
        target = OUT / f"{name}.{ext}"
        r = subprocess.run(
            [mmdc, "-i", str(src), "-o", str(target), "-p", str(cfg), *extra],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode != 0:
            print(f"diagrams: {name}.{ext} failed: {(r.stderr or r.stdout)[-300:]}")
            return False
        print(f"wrote {target.relative_to(ROOT)} ({target.stat().st_size} bytes)")
    return True


TERMINAL_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin: 0; background: #0f172a; }}
pre {{ margin: 0; padding: 28px 32px; color: #e2e8f0; font: 15px/1.45 "SF Mono", Menlo, Consolas, monospace;
      white-space: pre; display: inline-block; min-width: 1120px; }}
.t {{ color: #7dd3fc; }} .z {{ color: #86efac; }}
</style></head><body><pre>{body}</pre></body></html>"""


def _terminal_pngs() -> None:
    """The tour transcript's sections as terminal-styled PNGs, through Playwright's Chromium."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("diagrams: playwright not installed; terminal PNGs skipped")
        return
    transcript = ROOT / "docs" / "TOUR-TRANSCRIPT.md"
    if not transcript.exists():
        print("diagrams: docs/TOUR-TRANSCRIPT.md missing (make transcript); terminal PNGs skipped")
        return
    body = transcript.read_text().split("```")[1].strip("\n")
    sections = re.split(r"\n(?=== \d\. )", body)
    names = [
        "tour-1-every-gate",
        "tour-2-human-moment",
        "tour-3-counts",
        "tour-4-ablation",
        "tour-5-wire",
        "tour-6-runtime",
        "tour-7-sweep",
    ]
    from html import escape

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(device_scale_factor=2)
        for name, section in zip(names, sections, strict=False):
            text = escape(section)
            text = re.sub(r"^(== .*==)$", r'<span class="t">\1</span>', text, flags=re.M)
            text = re.sub(
                r"(reached rider: [^\n]*|zero leaks: [^\n]*|rejected 0|-> [a-z_]+)", r'<span class="z">\1</span>', text
            )
            page.set_content(TERMINAL_HTML.format(body=text))
            target = OUT / f"{name}.png"
            page.locator("pre").screenshot(path=str(target))
            print(f"wrote {target.relative_to(ROOT)} ({target.stat().st_size} bytes)")
        browser.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    mmdc = shutil.which("mmdc")
    if not mmdc:
        print("diagrams: mermaid-cli (mmdc) not installed; GitHub renders the Markdown itself. Mermaid PNGs skipped.")
    else:
        blocks = re.findall(r"```mermaid\n(.*?)```", SOURCE.read_text(), re.S)
        if len(blocks) != len(NAMES):
            print(f"diagrams: expected {len(NAMES)} mermaid blocks in {SOURCE.name}, found {len(blocks)}")
            return 1
        chromium = next((c for c in CHROMIUM_CANDIDATES if c and Path(c).exists()), None)
        config = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
        if chromium:
            config["executablePath"] = chromium
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            cfg = tmp / "puppeteer.json"
            cfg.write_text(json.dumps(config))
            for name, block in zip(NAMES, blocks, strict=False):
                if not _render_mermaid(mmdc, cfg, tmp, name, block, ("svg", "png")):
                    return 1
            for packet in sorted((ROOT / "docs" / "evidence").glob("*.md")):
                found = re.findall(r"```mermaid\n(.*?)```", packet.read_text(), re.S)
                if found and not _render_mermaid(mmdc, cfg, tmp, f"evidence-{packet.stem}", found[0], ("png",)):
                    return 1
    _terminal_pngs()
    return 0


if __name__ == "__main__":
    sys.exit(main())
