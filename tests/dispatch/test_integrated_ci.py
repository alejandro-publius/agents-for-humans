"""F73: the main repo's CI workflow, run in the integrated layout (scripts/integrated_ci.py)."""

from __future__ import annotations

import importlib.util
import sys

from le_dispatch.interfaces import ROOT


def _script():
    spec = importlib.util.spec_from_file_location("integrated_ci_script", ROOT / "scripts" / "integrated_ci.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["integrated_ci_script"] = module
    spec.loader.exec_module(module)
    return module


def test_every_workflow_step_is_read_in_order_with_block_runs_joined():
    """The parser reads the workflow the package ships: every run: line, in order, block runs as one command;
    so the transcript covers the whole workflow and not a hand-kept copy of it."""
    m = _script()
    assert m.WORKFLOW is not None and m.WORKFLOW.name in ("verify.yml", "dispatch-verify.yml")  # either layout
    steps = m.workflow_steps(m.WORKFLOW.read_text())
    commands = [c for _, c in steps]
    assert commands[0].startswith("python -m pip install") and "pip install -e" in commands[0]  # a block run
    assert "make verify" in commands and "make integrate-check" in commands
    assert any(c.startswith("git diff --exit-code") for c in commands)  # the determinism step
    assert commands.index("make verify") < commands.index("make integrate-check")
    assert all(name for name, _ in steps)
    sample = "\n".join(
        [
            "steps:",
            "      - name: one",
            "        run: make a",
            "      - name: two",
            "        run: |",
            "          make b",
            "          make c",
        ]
    )
    assert m.workflow_steps(sample) == [("one", "make a"), ("two", "make b && make c")]


def test_the_transcript_covers_the_workflow_and_says_how_it_went():
    """The committed transcript is the last run: one section per workflow step after the install, with an
    exit code, and a verdict line; whether it was green is the verdict's to say."""
    m = _script()
    report = (ROOT / "docs" / "reports" / "integrated-ci.md").read_text()
    steps = [(n, m.without_installs(c)) for n, c in m.workflow_steps(m.WORKFLOW.read_text())]
    steps = [(n, c) for n, c in steps if c]
    assert m.without_installs('pip install -e ".[a11y]" && playwright install chromium && make site-a11y') == (
        "make site-a11y"
    )
    for name, _ in steps:
        assert f"## {name}\n" in report, name
    assert report.count(": exit ") == len(steps) and "\nResult: " in report
    assert chr(0x2014) not in report and "/home/" not in report
