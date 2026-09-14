"""Secret scan for `make verify`: fails if any tracked file looks like it holds a key.

Patterns are assembled from fragments so this file never matches itself.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"scripts/secret_scan.py", "tests/conftest.py"}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "build",
    "dist",
    "node_modules",
    ".integrate-check",
    "htmlcov",
}

PATTERNS = [
    re.compile("AK" + "IA[0-9A-Z]{16}"),
    re.compile("aws_secret_" + "access_key\\s*[=:]\\s*\\S{20,}", re.I),
    re.compile("BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE " + "KEY"),
    re.compile("sk-" + "ant-[A-Za-z0-9_-]{20,}"),
    re.compile("(BART|OPENAI|ANTHROPIC)_API_" + "KEY\\s*[=:]\\s*['\"]?[A-Za-z0-9]{16,}"),
]


def tracked_files() -> list[str]:
    try:
        cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout
        files = [f for f in out.splitlines() if f and not any(part in SKIP_DIRS for part in Path(f).parts)]
        files = [f for f in files if not f.endswith((".pyc", ".pyo"))]  # compiled files fold string constants
    except (subprocess.CalledProcessError, FileNotFoundError):
        # a tree without git (a download, an archive): walk it, but never a virtualenv, a cache or a build folder,
        # which carry other people's example keys (botocore's STS examples, cryptography's PEM markers)
        files = [
            str(p.relative_to(ROOT))
            for p in ROOT.rglob("*")
            if p.is_file()
            and not any(part in SKIP_DIRS or part.startswith(".venv") or part.endswith(".egg-info") for part in p.parts)
        ]
    return files


def main() -> int:
    hits = []
    for rel in tracked_files():
        if rel in SKIP:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat in PATTERNS:
                if pat.search(line):
                    hits.append(f"{rel}:{i}: matches {pat.pattern[:24]}...")
    if hits:
        print("secret scan: FAILED")
        print("\n".join(hits))
        return 1
    print(f"secret scan: clean ({len(tracked_files())} tracked files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
