"""make rehearse: Sunday, offline, end to end, in a scratch copy of this package.

The laptop's sequence, with the fixtures standing in for the real exports and a scripted model standing in
for Bedrock: exports named like the real ones, the two environment variables, preflight, the policy
check, the red team, the ablation, the local evaluator, the evidence packets, the transcript, then the
docs check, which must fail until the fixture labels come off, and pass once they do. Every step prints
ok or FAIL; exit 1 on any FAIL. Nothing outside the scratch copy is touched.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv*",
    ".integrate-check",
    "data",
    "build",
    "dist",
    "*.egg-info",
    "node_modules",  # what the checks and the site leave behind; never part of a run
)


def run(step: str, cmd: list[str], cwd: Path, env: dict[str, str], expect_ok: bool = True) -> tuple[bool, str]:
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)
    ok = (r.returncode == 0) == expect_ok
    tail = (r.stdout.strip().splitlines() or [""])[-1][:110]
    print(f"{'ok  ' if ok else 'FAIL'} {step:<44} {time.time() - t0:5.1f}s  {tail}")
    return ok, r.stdout + r.stderr


def main() -> int:
    py = sys.executable
    with tempfile.TemporaryDirectory(prefix="le-rehearsal-") as tmp:
        repo = Path(tmp) / "last-elevator-dispatch"
        shutil.copytree(ROOT, repo, ignore=IGNORE)
        exports = repo / "kb" / "export"
        exports.mkdir(parents=True)
        shutil.copy(repo / "fixtures" / "kb.json", exports / "kb-labels-v1.json")
        shutil.copy(repo / "fixtures" / "cases.json", exports / "cases-v1.json")
        env = dict(os.environ)
        env.update(
            {
                "LE_KB_EXPORT": str(exports / "kb-labels-v1.json"),
                "LE_CASES_EXPORT": str(exports / "cases-v1.json"),
                "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent/rehearsal-credentials",
                "AWS_EC2_METADATA_DISABLED": "true",
            }
        )
        for name in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_BEARER_TOKEN_BEDROCK"):
            env.pop(name, None)
        print(f"rehearsal in {repo}: the fixtures stand in for the exports, nothing is called\n")
        results: list[bool] = []
        steps: list[tuple[str, list[str], bool]] = [
            ("preflight --quick (exports set, no credentials)", [py, "scripts/preflight.py", "--quick"], True),
            ("policy-check (the case-backed policy against itself)", [py, "scripts/policy_check.py"], True),
            ("red-team", [py, "scripts/red_team.py"], True),
            ("red-team --exhaustive", [py, "scripts/red_team.py", "--exhaustive"], True),
            ("ablation", [py, "scripts/ablation.py"], True),
            ("convergence", [py, "scripts/convergence.py"], True),
            ("agentcore-eval-local", [py, "scripts/agentcore_eval_local.py"], True),
            ("agentcore-eval (dry run)", [py, "scripts/agentcore_eval.py", "--dry-run"], True),
            ("agentcore-policy (dry run, service-model check)", [py, "scripts/agentcore_policy.py"], True),
            ("agentcore-memory (dry run, service-model check)", [py, "scripts/agentcore_memory.py"], True),
            ("evaluator-zip (the Lambda package, verified)", [py, "scripts/evaluator_zip.py"], True),
            ("gen_cedar", [py, "scripts/gen_cedar.py"], True),
            ("wire (the real Bedrock adapter, stand-in client)", [py, "scripts/bedrock_wire.py"], True),
            ("wire-convergence (the personas through the adapter)", [py, "scripts/wire_convergence.py"], True),
            ("runtime-sweep (every case through the entrypoint)", [py, "scripts/runtime_sweep.py"], True),
            ("impact (what riders faced, from the archive)", [py, "scripts/impact.py"], True),
            (
                "report --archive (the archive's week replayed for the synthetic riders)",
                [
                    py,
                    "scripts/quiet_report.py",
                    "--archive",
                    "fixtures/archive_fixture.sqlite",
                    "--out",
                    "/tmp/le-quiet-archive.json",
                ],
                True,
            ),
            ("evidence packets", [py, "scripts/evidence_packet.py"], True),
            ("eval-live (dry run: no credentials)", [py, "scripts/eval_live.py"], True),
            ("eval-live --stand-in (the live path, nothing called)", [py, "scripts/eval_live.py", "--stand-in"], True),
            ("demo-live --stand-in (one case, the packet)", [py, "scripts/demo_live.py", "--stand-in"], True),
            ("verify-claims (the counts hold on the exports)", [py, "scripts/verify_claims.py"], True),
            (
                "check-docs must FAIL: results are claimable, labels still say fixture",
                [py, "scripts/check_docs.py"],
                False,
            ),
        ]
        for step, cmd, expect_ok in steps:
            ok, _ = run(step, cmd, repo, env, expect_ok)
            results.append(ok)
        # the laptop's edit: drop the fixture labels in the documents the check reads (post 2 in both copies)
        for name in (
            "README-sections.md",
            "devpost.md",
            "FAQ.md",
            "posts/02-agents-for-humans-two-stage-gate.md",
            "posts/publish-ready/post-2.md",
        ):
            f = repo / "docs" / name
            text = re.sub(r"fixture\s+run\b", "laptop run", f.read_text())
            f.write_text(re.sub(r"pending\s+the\s+laptop\s+rerun", "rerun done", text))
        ok, _ = run("check-docs after the label edit", [py, "scripts/check_docs.py"], repo, env, True)
        results.append(ok)
        ok, _ = run(
            "results say claimable and name the exports",
            [
                py,
                "-c",
                (
                    "import json; d=json.load(open('results/red_team.json'))['provenance']; "
                    "assert d['claimable'] and not d['source']['fixture'], d; "
                    "assert 'kb-labels-v1.json' in d['source']['kb'], d; "
                    "print('claimable', d['claimable'], d['source']['kb'])"
                ),
            ],
            repo,
            env,
            True,
        )
        results.append(ok)
        failed = results.count(False)
        print(f"\nrehearsal: {'ok' if not failed else 'FAILED'} ({len(results) - failed}/{len(results)} steps)")
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
