"""make integrate-ci: the CI workflow the main repo receives, run step by step in the integrated layout.

    python scripts/integrated_ci.py            # about a quarter of an hour; writes docs/reports/integrated-ci.md

`scripts/integrate.py` copies the package into an empty tree the way it lands in `agents-for-humans`
(`tests/dispatch/`, `docs/`, no package README, no package Makefile); this script adds the package's
Makefile and pyproject as stand-ins for the targets and extras the owner adds by hand (docs/INTEGRATION.md
section 1), makes the tree a git repository so the determinism step has something to diff, and runs every
`run:` line of `.github/workflows/verify.yml` there, in order, with its exit code and its last lines. The
install step is skipped (this environment is the install). The transcript is the answer to one question the
day before a merge: will the workflow that `make integrate` places be green in the main repo, or will it be
red on the first page a judge opens.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "reports" / "integrated-ci.md"
WORK = ROOT / "build" / "integrated-ci"
WORKFLOWS = ROOT / ".github" / "workflows"
# the package's name for the workflow, then the name make integrate gives it in the main repo
WORKFLOW = next((p for p in (WORKFLOWS / "verify.yml", WORKFLOWS / "dispatch-verify.yml") if p.exists()), None)
# the owner's own README, Makefile and pyproject stand where the main repo has them (INTEGRATION.md section 1)
STAND_INS = ("README.md", "Makefile", "pyproject.toml")


def workflow_steps(text: str) -> list[tuple[str, str]]:
    """(name, command) for every step with a run: line, in order; a block run is joined with &&."""
    steps: list[tuple[str, str]] = []
    name = ""
    for i, line in enumerate(lines := text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("- name:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped == "run: |":
            block = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith(" " * 10) and nxt.strip():
                    block.append(nxt.strip())
                else:
                    break
            steps.append((name, " && ".join(block)))
        elif stripped.startswith("run:"):
            steps.append((name, stripped.split(":", 1)[1].strip()))
    return steps


INSTALLS = ("python -m pip ", "pip install ", "playwright install")


def without_installs(cmd: str) -> str:
    """The step's command without its environment setup: this environment is the install."""
    return " && ".join(part for part in cmd.split(" && ") if not part.strip().startswith(INSTALLS))


def sh(cmd: str, cwd: Path, timeout: int = 3600) -> tuple[int, str, float]:
    start = time.time()
    try:
        out = subprocess.run(
            ["bash", "-o", "pipefail", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return out.returncode, out.stdout + out.stderr, time.time() - start
    except subprocess.TimeoutExpired as exc:
        return 124, f"timed out after {timeout}s\n{exc.stdout or ''}", time.time() - start


def provisional_report(steps: list[tuple[str, str]]) -> str:
    """The tree's copy of the transcript, for this run: every step pending. The tree's own tests check that
    the transcript covers the workflow, and this run is what produces it."""
    lines = ["# The main repo's CI, run in the integrated layout", "", "This run is in progress.", ""]
    for name, cmd in steps:
        lines += [f"## {name}", "", f"`{cmd}`: exit pending", ""]
    return "\n".join(lines + ["Result: pending.", ""])


def integrated_tree(tree: Path, steps: list[tuple[str, str]]) -> str:
    """The package copied into `tree` as it lands in the main repo, with the stand-ins, as a git repository."""
    shutil.rmtree(tree, ignore_errors=True)
    (tree / "results").mkdir(parents=True)
    shutil.copy(ROOT / "results" / "policy_agreement.json", tree / "results" / "policy_agreement.json")
    out = subprocess.run(
        [sys.executable, "scripts/integrate.py", "--into", str(tree), "--yes"], cwd=ROOT, capture_output=True, text=True
    )
    if out.returncode != 0:
        raise SystemExit(f"integrate failed:\n{out.stdout}{out.stderr}")
    for name in STAND_INS:
        shutil.copy(ROOT / name, tree / name)
    (tree / "docs" / "reports" / "integrated-ci.md").write_text(provisional_report(steps))
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.email=ci@example", "-c", "user.name=integrated-ci", "commit", "-q", "-m", "integrated"],
    ):
        subprocess.run(cmd, cwd=tree, check=True, capture_output=True)
    return out.stdout.strip().splitlines()[-1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="run only the steps whose name contains this text")
    args = ap.parse_args(argv)
    if WORKFLOW is None:
        raise SystemExit("integrate-ci: no verify.yml or dispatch-verify.yml under .github/workflows")
    steps = [(n, c) for n, c in ((n, without_installs(c)) for n, c in workflow_steps(WORKFLOW.read_text())) if c]
    if args.only:
        steps = [(n, c) for n, c in steps if args.only in n]
    tree = WORK / "main-repo"
    copied = re.sub(re.escape(str(tree)) + "/?", "", integrated_tree(tree, steps))
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    lines = [
        "# The main repo's CI, run in the integrated layout",
        "",
        f"`make integrate-ci` on {stamp}: `scripts/integrate.py` copied the package into an empty tree the way",
        "it lands in `agents-for-humans` (`tests/dispatch/`, `docs/`, no package README, no package Makefile),",
        "the package's README, Makefile and pyproject stood in for the main repo's own (the targets and extras",
        "the owner adds by hand, `docs/INTEGRATION.md` section 1), the tree became a git repository, and every",
        "`run:` line of",
        "`.github/workflows/verify.yml` (the workflow `make integrate` places as `dispatch-verify.yml`) ran",
        "there in order. The install step is this environment. Exit codes and last lines below; paths in the",
        "scratch tree are shortened. Anything red here would be red on the main repo's Actions page after the",
        "merge, which is the first page some judges open.",
        "",
        f"Integrate: `{copied}`.",
        "",
    ]
    failures = 0
    for name, cmd in steps:
        code, out, took = sh(cmd, tree)
        tail = "\n".join(out.rstrip().splitlines()[-6:]) or "(no output)"
        tail = re.sub(re.escape(str(tree)) + "/?", "", tail)
        tail = "\n".join(line for line in tail.splitlines() if not line.startswith("make[1]: Leaving directory"))
        tail = tail.replace(chr(0x2014), "-")  # never an em dash in a shipped document
        lines += [f"## {name}", "", f"`{cmd}`: exit {code}, {took:.0f}s", "", "```", tail, "```", ""]
        failures += int(code != 0)
        print(f"{'ok ' if code == 0 else 'RED'} {took:5.0f}s  {cmd[:100]}")
    verdict = "every step exited 0" if not failures else f"{failures} step(s) failed"
    lines += [f"Result: {verdict}.", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    print(f"wrote {REPORT.relative_to(ROOT)}: {verdict}")
    shutil.rmtree(WORK, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
