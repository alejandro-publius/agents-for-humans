"""The image check's probe (the entrypoint and the app module, invoked with only the runtime image's
requirements) passes under the current interpreter; CI runs it in a virtualenv built from that file alone."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys

import pytest
from le_dispatch.interfaces import ROOT


def test_the_probe_passes_here():
    pytest.importorskip("bedrock_agentcore")  # the aws extra; the README's plain install skips this, as it says
    spec = importlib.util.spec_from_file_location("image_check_script", ROOT / "scripts" / "image_check.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    run = subprocess.run([sys.executable, "-c", script.PROBE], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.strip().splitlines()[-1].startswith("probe: ok (quiet, sent, the app built twice)")
    assert script.REQUIREMENTS.exists()
    names = [
        re.split(r"[\[=<>~!]", line)[0]
        for line in script.REQUIREMENTS.read_text().splitlines()
        if line and not line.startswith("#")
    ]

    assert names == ["strands-agents", "pydantic", "bedrock-agentcore"]
