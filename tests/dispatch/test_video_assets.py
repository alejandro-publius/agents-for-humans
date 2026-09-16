"""H2: every command behind the video runs and prints the line it claims (scripts/video_assets.py)."""

from __future__ import annotations

import importlib.util
import re
import sys

from le_dispatch.interfaces import ROOT


def test_every_moment_has_a_command_a_freeze_line_and_a_place_in_the_script():
    spec = importlib.util.spec_from_file_location("video_assets_script", ROOT / "scripts" / "video_assets.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["video_assets_script"] = module
    spec.loader.exec_module(module)
    script = (ROOT / "docs" / "video-script.md").read_text()
    keys = [m.key for m in module.MOMENTS]
    assert len(keys) == len(set(keys)) and {
        "hook_cancel",
        "guide_before_tool",
        "guide_after_model",
        "interrupt",
    } <= set(keys)
    assert {"quiet_report", "eval_table", "red_team", "trace"} <= set(keys)
    files = [p for p in (ROOT / "Makefile", ROOT / "dispatch.mk") if p.exists()]  # the main repo includes dispatch.mk
    targets = {t for p in files for t in re.findall(r"^([a-z][a-z0-9-]*):", p.read_text(), re.M)} if files else None
    for m in module.MOMENTS:
        assert m.command.startswith("make "), m.key
        assert targets is None or m.command.split()[1] in targets, m.key
        assert m.freeze and m.at.split(" ")[0] in script, m.key  # the moment's start time is in the script
    # the freeze lines match what the fast commands print (the trace demo and the after-dark demo, the report)
    outputs = {}
    for m in module.MOMENTS:
        if m.key in (
            "brief",
            "note",
            "hook_cancel",
            "guide_before_tool",
            "guide_after_model",
            "final_plan",
            "trace",
            "interrupt",
            "quiet_report",
            "eval_table",
        ):
            outputs.setdefault(tuple(m.argv), module.run(m.argv))
            for pattern, match in module.freeze_lines(outputs[tuple(m.argv)], m.freeze):
                assert match is not None, (m.key, pattern)
    text = module.commands_md({m.key: outputs.get(tuple(m.argv), "") for m in module.MOMENTS})
    assert text.count("## ") == len(module.MOMENTS) and "\u2014" not in text


def test_the_generated_document_and_renders_are_current():
    """docs/video/commands.md names every moment in MOMENTS and both renders exist (make video-assets)."""
    doc = (ROOT / "docs" / "video" / "commands.md").read_text()
    assert doc.count("## ") == 13 and "[not printed" not in doc
    for name in ("trace.png", "eval_table.png"):
        assert (ROOT / "docs" / "video" / name).stat().st_size > 10000


def test_the_storyboard_carries_every_voice_line_and_every_moment():
    """docs/video/storyboard.md (make video-assets) is the script's sections in order with every VO line
    and every screen moment placed under its time, so the cut has one page to work from."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("video_assets_storyboard", ROOT / "scripts" / "video_assets.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["video_assets_storyboard"] = module
    spec.loader.exec_module(module)
    board = (ROOT / "docs" / "video" / "storyboard.md").read_text()
    script = (ROOT / "docs" / "video-script.md").read_text()
    voice = [line[3:].strip() for line in script.splitlines() if line.startswith("VO:")]
    assert len(voice) > 60 and all(f"- {v}" in board for v in voice)
    for m in module.MOMENTS:
        assert f"| {m.title} | `{m.command}` |" in board, m.key
    sections = [line for line in script.splitlines() if line.startswith("## ") and line[3].isdigit()]
    assert all(f"{s}\n" in board for s in sections) and chr(0x2014) not in board
