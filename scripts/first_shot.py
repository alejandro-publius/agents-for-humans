"""make first-shot: the video's first shot as an animated GIF and a still, for the README and the gallery.

    python scripts/first_shot.py            # docs/screenshots/00-first-shot.gif and 00-first-shot.png
    pip install -e '.[a11y]' && playwright install chromium   # Playwright, Chromium and Pillow, once

`make demo-one-brief` prints one run in plain lines: what code decided, what the model tried, what
stopped it, what reached the rider. This renders those lines into a terminal the way they arrive, one
per frame, and writes the frames as a GIF (about eight seconds, looping) plus the last frame as a PNG.
The lines come from the same script the tour runs, so the picture cannot say something the run does
not; the README shows the GIF under its first paragraph with the lines as alt text, and the evidence
site shows the lines as text first, so a screen reader gets the run before the picture.
"""

from __future__ import annotations

import html
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
PY = sys.executable

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin: 0; background: #0f172a; }}
.wrap {{ width: 960px; box-sizing: border-box; padding: 24px 28px; min-height: 420px; }}
pre {{ margin: 0; white-space: pre-wrap; font: 15px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  color: #e2e8f0; }}
.t {{ color: #7dd3fc; }} .stop {{ color: #fca5a5; }} .rider {{ color: #86efac; }}
.rule {{ color: #fde68a; font-weight: 600; }}
.cursor {{ display: inline-block; width: 9px; height: 17px; background: #e2e8f0; vertical-align: -3px; }}
</style></head><body><div class="wrap"><pre><span class="t">$ make demo-one-brief</span>
{lines}<span class="cursor"></span></pre></div></body></html>"""


def brief_lines() -> list[str]:
    out = subprocess.run([PY, "scripts/demo_one.py", "--brief"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.rstrip("\n").splitlines()


def render(lines: list[str]) -> str:
    body = []
    for line in lines:
        text = html.escape(line)
        if line.startswith("  what stopped it"):
            text = f'<span class="stop">{text}</span>'
        elif line.startswith("what reached the rider") or line.startswith('  "'):
            text = f'<span class="rider">{text}</span>'
        elif line.startswith("models propose"):
            text = f'<span class="rule">{text}</span>'
        body.append(text)
    return "".join(t + "\n" for t in body)


def main(argv=None) -> int:
    try:
        from PIL import Image
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("first-shot: playwright or Pillow not installed; skipped")
        return 0
    lines = brief_lines()
    OUT.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    durations: list[int] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 960, "height": 480})
        for n in range(len(lines) + 1):
            page.set_content(PAGE.format(lines=render(lines[:n])))
            shot = page.locator("div.wrap").screenshot()
            frames.append(Image.open(io.BytesIO(shot)).convert("P", palette=Image.ADAPTIVE, colors=64))
            durations.append(500 if n < len(lines) else 3000)
        browser.close()
    gif = OUT / "00-first-shot.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=False)
    png = OUT / "00-first-shot.png"
    frames[-1].convert("RGB").save(png)
    print(f"wrote {gif.relative_to(ROOT)} ({len(frames)} frames, {gif.stat().st_size} bytes), {png.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
