"""Rewrite every ``<!-- claim:key -->NUMBER`` in README.md with the current value from results/.

This is the only way a number gets into the README: it is copied from ``results/*.json``, never
typed. ``scripts/verify_claims.py`` then checks the README against the same files.
Run ``make evals`` (and ``make evals ABLATE=1``) first.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_claims import CLAIM_RE, README, RESULTS_DIR, decimals_shown, lookup  # noqa: E402


def render(readme: Path = README, results_dir: Path = RESULTS_DIR) -> int:
    body = readme.read_text()
    changed = 0
    missing: list[str] = []

    def sub(m: re.Match[str]) -> str:
        nonlocal changed
        key, shown, pct = m.group(1), m.group(2), m.group(3)
        value, err = lookup(key, results_dir)
        if err:
            missing.append(f"{key}: {err}")
            return m.group(0)
        decimals = decimals_shown(shown)
        if decimals:
            rendered = f"{round(float(value), decimals):.{decimals}f}"
        else:
            rendered = str(int(round(float(value))))
        if rendered != shown:
            changed += 1
        prefix = m.group(0)[: m.group(0).rfind(shown + pct)]
        return f"{prefix}{rendered}{pct}"

    new_body = CLAIM_RE.sub(sub, body)
    if missing:
        for line in missing:
            print(f"render_claims: {line}", file=sys.stderr)
        return 1
    if new_body != body:
        readme.write_text(new_body)
    print(f"render_claims: {changed} claim(s) updated from results/")
    return 0


if __name__ == "__main__":
    sys.exit(render())
