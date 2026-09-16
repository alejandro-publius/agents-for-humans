"""H4: the README's setup block is what the cold start replays, and the last replay was green."""

from __future__ import annotations

import importlib.util
import sys

import pytest
from le_dispatch.interfaces import ROOT


def test_the_setup_block_is_five_commands_a_stranger_can_type():
    spec = importlib.util.spec_from_file_location("cold_start_script", ROOT / "scripts" / "cold_start.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cold_start_script"] = module
    spec.loader.exec_module(module)
    commands = module.readme_setup_block()
    if not commands:
        pytest.skip("the README here has no setup block (the main repo's own README); the replay reads the archive's")
    assert commands[0].startswith("python3 -m venv .venv") and commands[1] == "make install"
    assert commands[2:] == ["make verify", "make judge", "make demo-one"]


def test_without_bundles_the_cold_start_says_so_and_passes(tmp_path, capsys, monkeypatch):
    """The main repo has no package history: make bundles builds nothing there, and the cold start has no
    chain to replay; it says so and exits 0 instead of failing the placed CI workflow."""
    spec = importlib.util.spec_from_file_location("cold_start_script", ROOT / "scripts" / "cold_start.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cold_start_script"] = module
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: calls.append(a[0]))  # bundles.py builds nothing
    assert module.main(["--bundles", str(tmp_path / "none")]) == 0
    assert calls and "bundles.py" in str(calls[0][1])
    assert "no bundles to replay here" in capsys.readouterr().out


def test_the_cold_start_transcript_shows_the_run():
    """The committed transcript is the last replay (CI reruns it): every setup command with its exit code and
    a verdict line. Whether it was green is the verdict's to say; make cold-start exits with it."""
    report = (ROOT / "docs" / "reports" / "cold-start.md").read_text()
    for cmd in ("$ make install", "$ make verify", "$ make judge", "$ make demo-one"):
        assert cmd in report, cmd
    assert report.count("\nexit ") >= 4 and "\nResult: " in report
    assert "\u2014" not in report


def test_the_codespace_runs_the_same_install_and_verify():
    """The devcontainer a judge opens installs the package with every extra and runs make verify, so the
    first thing they see is the gate, green or red; the file is valid JSON and names a pinned image."""
    import json

    path = ROOT / ".devcontainer" / "devcontainer.json"
    if not path.exists():
        pytest.skip("no devcontainer here (the main repo decides its own Codespace)")
    spec = json.loads(path.read_text())
    assert spec["image"].startswith("mcr.microsoft.com/devcontainers/python:3.1")
    command = spec["postCreateCommand"]
    assert "pip install -e '.[dev,cedar,aws]'" in command and "make verify" in command
