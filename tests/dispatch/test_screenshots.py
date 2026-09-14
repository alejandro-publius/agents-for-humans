"""H3: the numbered submission screenshots exist, are indexed, and the devpost refers to them by number."""

from __future__ import annotations

import re

from le_dispatch.interfaces import ROOT

EXPECTED = {
    "01-decision-card.png",
    "02-quiet-report.png",
    "03-trace.png",
    "04-eval-table.png",
    "05-red-team.png",
    "06-architecture.png",
    "07-claims-badge.png",
    "09-dataset-header.png",
}


def test_the_screenshots_are_present_indexed_and_referenced():
    folder = ROOT / "docs" / "screenshots"
    present = {p.name for p in folder.glob("*.png")}
    assert EXPECTED <= present, EXPECTED - present
    for name in EXPECTED:
        assert (folder / name).stat().st_size > 10000, name
    index = (folder / "README.md").read_text()
    for number in ("01", "02", "03", "04", "05", "06", "07", "08", "09"):
        assert f"| {number} |" in index, number
    assert "08-axe.png" in index and "not generated here" in index  # the laptop's, said plainly
    devpost = (ROOT / "docs" / "devpost.md").read_text()
    section = devpost[devpost.index("## Screenshots") :]
    for number in ("01", "02", "03", "04", "05", "06", "07", "08", "09"):
        assert re.search(rf"\b{number} [a-z]", section), number
    assert "docs/screenshots/README.md" in section and "\u2014" not in index


def test_the_first_shot_is_the_brief_as_a_gif_and_a_still_and_the_readme_shows_it():
    """docs/screenshots/00-first-shot.gif is the brief's lines arriving one per frame, 00-first-shot.png the
    last frame; the index has row 00, the devpost refers to it, the README shows the GIF with words as alt
    text, and the renderer colours only the lines that mean something to a rider."""
    import importlib.util
    import sys

    folder = ROOT / "docs" / "screenshots"
    assert (folder / "00-first-shot.gif").stat().st_size > 50000
    assert (folder / "00-first-shot.png").stat().st_size > 10000
    assert "| 00 |" in (folder / "README.md").read_text()
    devpost = (ROOT / "docs" / "devpost.md").read_text()
    assert re.search(r"\b00 the first shot", devpost[devpost.index("## Screenshots") :])
    readme = ROOT / "README.md"
    if readme.exists() and "## In one screen" in readme.read_text():
        assert re.search(r"!\[[^\]]{20,}\]\(docs/screenshots/00-first-shot\.gif\)", readme.read_text())
    spec = importlib.util.spec_from_file_location("first_shot_script", ROOT / "scripts" / "first_shot.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["first_shot_script"] = module
    spec.loader.exec_module(module)
    lines = module.brief_lines()
    assert lines[0].startswith("code decided:") and lines[-1] == "models propose, code decides"
    rendered = module.render(lines)
    assert rendered.count('class="stop"') == 3 and 'class="rule"' in rendered and 'class="rider"' in rendered
    assert "FAKE-E7" in rendered and "&#x27;" in rendered  # escaped, never raw
