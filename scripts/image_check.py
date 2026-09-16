"""make image-check: does the runtime image's requirements file carry everything the entrypoint needs?

`agentcore configure -r infra/agentcore/runtime/requirements.txt` builds the image from that file and the
project directory. A package the entrypoint imports that is not on the list crashes the container at start,
on Sunday, in the console. This script builds a virtualenv from that requirements file alone, then runs a
probe in it: imports the entrypoint and the toolkit-facing app module, runs a quiet invocation and a sent
one with the scripted model, and builds the AgentCore app. The venv is the only thing installed; nothing is
called. Needs the package index (pip); about a minute.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "infra" / "agentcore" / "runtime" / "requirements.txt"

PROBE = r"""
import importlib.util, os, sys, tempfile
from pathlib import Path
data = Path(tempfile.mkdtemp(prefix="image-check-"))
sys.path.insert(0, os.getcwd())

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

ep = load("entrypoint", "infra/agentcore/runtime/entrypoint.py")
from le_dispatch.interfaces import fixture_policy
from le_dispatch.messages import composed_plan
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call

kb, policy = fixture_policy()

def factory(trip, decision):
    d = decision
    draft = tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1")
    return ScriptedModel([draft, plan_call(composed_plan(d), "p1")])

common = dict(model_factory=factory, kb=kb, policy=policy, data_dir=data)
quiet = ep.handle({"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": []}, **common)
sent = ep.handle({"rider_id": "r1", "origin": "DELN", "destination": "EMBR", "outages": ["DELN-E1"]}, **common)
assert quiet["state"] == "quiet" and sent["state"] == "sent", (quiet, sent)
app = ep.make_runtime(factory, kb=kb, policy=policy, data_dir=data)
module = load("rt_app", "infra/agentcore/runtime/app.py")
assert type(app).__name__ == type(module.app).__name__ == "BedrockAgentCoreApp"
import strands, pydantic, bedrock_agentcore  # noqa: E401,F401
from importlib.metadata import version
print(
    "probe: ok (quiet, sent, the app built twice) on python "
    + sys.version.split()[0]
    + " with strands-agents " + version("strands-agents")
    + ", pydantic " + version("pydantic")
    + ", bedrock-agentcore " + version("bedrock-agentcore")
    + "; observability: " + ep.setup_observability()
)
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venv", default=None, help="reuse this virtualenv directory (default: a temporary one)")
    ap.add_argument("--requirements", default=str(REQUIREMENTS))
    args = ap.parse_args(argv)
    t0 = time.time()
    tmp = None
    if args.venv:
        venv = Path(args.venv)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="le-image-check-")
        venv = Path(tmp.name) / "venv"
    try:
        if not (venv / "bin" / "python").exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        py = venv / "bin" / "python"
        print(f"installing {Path(args.requirements).relative_to(ROOT)} into a fresh virtualenv (nothing else)")
        install = subprocess.run(
            [str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", args.requirements],
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            print(install.stdout[-2000:] + install.stderr[-2000:])
            print("image-check: FAILED (pip install)")
            return 1
        probe = subprocess.run([str(py), "-c", PROBE], cwd=ROOT, capture_output=True, text=True)
        tail = (probe.stdout.strip().splitlines() or [""])[-1]
        if probe.returncode != 0:
            print(probe.stdout[-3000:] + probe.stderr[-3000:])
            print("image-check: FAILED (the entrypoint needs something the requirements file does not carry)")
            return 1
        print(tail)
        print(f"image-check: ok ({time.time() - t0:.0f}s)")
        return 0
    finally:
        if tmp is not None:
            tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
