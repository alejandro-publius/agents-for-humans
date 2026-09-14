"""Verify every number claimed in README.md against results/*.json.

A claim is written in the README as an HTML comment immediately before the number::

    <!-- claim:summary.accuracy_pct -->100.0%
    <!-- claim:ablation.suites.harness_hook.cases_passed -->**1**

The key is ``<results file stem>.<dotted path>``: ``summary.accuracy_pct`` reads
``results/summary.json`` and looks up ``["accuracy_pct"]``. The README number must equal the
result rounded to the precision the README shows.

Fails (exit 1) on: a mismatch, a claim whose result file or field is missing, a README with no
claims at all, or a percentage in the README that is not marked as a claim.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
RESULTS_DIR = REPO_ROOT / "results"
# Every document whose numbers must come from results/ (claims) or be marked TODO.
CLAIM_DOCS = (
    README,
    REPO_ROOT / "docs" / "devpost.md",
    REPO_ROOT / "docs" / "VIDEO.md",
    *sorted((REPO_ROOT / "docs" / "posts").glob("*.md")),
)

CLAIM_RE = re.compile(r"<!--\s*claim:([A-Za-z0-9_.\-]+)\s*-->\s*\**\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*(%?)")
PERCENT_RE = re.compile(r"(?<![\w.\-])(\d+(?:\.\d+)?)%")


def lookup(key: str, results_dir: Path) -> tuple[Any, str | None]:
    stem, _, path = key.partition(".")
    file = results_dir / f"{stem}.json"
    if not file.exists():
        return None, f"no results file {file.relative_to(REPO_ROOT)}"
    node: Any = json.loads(file.read_text())
    for part in path.split(".") if path else []:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None, f"field {path!r} not found in {file.name}"
    if isinstance(node, bool) or not isinstance(node, int | float):
        return None, f"{key} is not a number in results (got {type(node).__name__})"
    return node, None


def decimals_shown(text: str) -> int:
    return len(text.split(".")[1]) if "." in text else 0


# The dispatch package ships its own claim rows (le_dispatch/claims.py): one (file, json path,
# comparison, expected) per number its documents cite. They are merged here rather than copied, so this
# repo keeps one entry point. The two results files this repo kept at integration (results/red_team.json
# and results/quiet.json have this repo's own shape, not the package's) are skipped with a printed reason.
PACKAGE_CLAIMS_SKIP_FILES = ("red_team.json", "quiet.json")


def verify_package_claims(results_dir: Path = RESULTS_DIR) -> int:
    """Run the dispatch package's claim table. Returns the number that did not hold."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from le_dispatch.claims import CLAIMS, verify_all
    except ImportError:
        return 0
    rows = [c for c in CLAIMS if c.file not in PACKAGE_CLAIMS_SKIP_FILES]
    skipped = len(CLAIMS) - len(rows)
    bad = 0
    for claim, ok, actual in verify_all(results_dir=results_dir, claims=rows):
        if not ok:
            print(f"BAD {claim.id:<28} {claim.file} {claim.path} {claim.op} {claim.expected!r} (actual {actual!r})")
            bad += 1
    print(
        f"dispatch package claims: {len(rows) - bad}/{len(rows)} verified"
        f" ({skipped} skipped: this repo kept its own {', '.join(PACKAGE_CLAIMS_SKIP_FILES)})"
    )
    return bad


def verify(readme: Path = README, results_dir: Path = RESULTS_DIR) -> int:
    docs = CLAIM_DOCS if readme == README else (readme,)
    total = 0
    failures: list[str] = []
    for doc in docs:
        if not doc.exists():
            continue
        n, doc_failures = verify_doc(doc, results_dir)
        total += n
        failures.extend(f"{doc.relative_to(REPO_ROOT)}: {f}" for f in doc_failures)
    if failures:
        print("\nverify_claims: FAILED", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"verify_claims: {total} claim(s) match results/ across {len(docs)} document(s)")
    return 0


def verify_doc(doc: Path, results_dir: Path) -> tuple[int, list[str]]:
    body = doc.read_text()
    claims = CLAIM_RE.findall(body)
    failures: list[str] = []

    if not claims and doc == README:
        failures.append("no <!-- claim:key --> markers; every reported number must be a claim")

    for key, shown, pct in claims:
        value, err = lookup(key, results_dir)
        if err:
            failures.append(f"{key}: {err}")
            continue
        shown_num = float(shown.replace(",", ""))
        rounded = round(float(value), decimals_shown(shown))
        ok = abs(shown_num - rounded) < 1e-9
        status = "OK      " if ok else "MISMATCH"
        print(f"{status} {key} README={shown}{pct} results={value}")
        if not ok:
            failures.append(f"{key}: README says {shown}{pct}, results say {value}")

    # Every percentage in the document must be a claim (no hand-typed numbers).
    claimed_spans = {m.end(2) for m in CLAIM_RE.finditer(body)}
    for m in PERCENT_RE.finditer(body):
        if m.end(1) not in claimed_spans:
            line = body.count("\n", 0, m.start()) + 1
            failures.append(f"line {line}: percentage {m.group(0)!r} is not marked as a claim")
    return len(claims), failures


if __name__ == "__main__":
    sys.exit(verify() + verify_package_claims())
