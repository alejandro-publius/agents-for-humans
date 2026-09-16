"""Regex secret scan over every git-tracked file. Part of ``make verify``; no network, no binary.

Exit 1 and print ``file:line: <pattern name>`` for each hit, with the matched text redacted.
Patterns cover AWS keys, Anthropic/OpenAI/GitHub tokens, BART API keys (XXXX-XXXX-XXXX-XXXX),
private-key blocks, and ``NAME=value`` assignments of known secret variables.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PATTERNS: dict[str, re.Pattern[str]] = {
    "aws-access-key-id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws-secret-access-key": re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}"),
    "anthropic-api-key": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai-api-key": re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_\-]{20,}"),
    "github-token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b"),
    "bart-api-key": re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b"),
    "private-key-block": re.compile(r"-----BEGIN (?:RSA|EC|DSA|OPENSSH|PGP) PRIVATE KEY-----"),
    "secret-assignment": re.compile(
        r"(?i)\b(?:BART_API_KEY|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|AWS_BEARER_TOKEN_BEDROCK|"
        r"ANTHROPIC_API_KEY|OPENAI_API_KEY)\s*=\s*['\"]?[A-Za-z0-9/+_\-]{8,}"
    ),
}

# Files that legitimately contain the pattern *shapes* (never values): this scanner and its test.
SELF = {"scripts/secret_scan.py", "tests/test_secret_scan.py"}


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [root / p for p in out.decode().split("\0") if p]


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """Return (line_number, pattern_name, redacted_match) for every hit."""
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS.items():
            for m in pattern.finditer(line):
                token = m.group(0)
                hits.append((lineno, name, token[:6] + "…" + token[-2:]))
    return hits


def scan_files(files: list[Path], root: Path) -> list[str]:
    findings = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if rel in SELF or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, name, redacted in scan_text(text):
            findings.append(f"{rel}:{lineno}: {name} ({redacted})")
    return findings


def main() -> int:
    files = tracked_files(REPO_ROOT)
    findings = scan_files(files, REPO_ROOT)
    if findings:
        print("secret_scan: FAILED", file=sys.stderr)
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"secret_scan: {len(files)} tracked files clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
