"""make coverage: line coverage of the package by the offline tests, written to results/coverage.json.

Runs the whole suite under coverage.py (the network blocked and the keys stripped as always), then writes
the totals and the least-covered modules. The number the README cites comes from that file and a claim
pins its floor; scripts/ are not measured (they are exercised by the make targets CI runs).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "coverage.json"
SOURCES = "le_dispatch,infra"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RESULTS))
    args = ap.parse_args(argv)
    try:
        import coverage  # noqa: F401
    except ImportError:
        print("coverage is not installed: pip install -e '.[dev]'")
        return 1
    data_file = ROOT / ".coverage"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--data-file={data_file}",
            f"--source={SOURCES}",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if run.returncode != 0:
        print(run.stdout[-3000:] + run.stderr[-3000:])
        print("coverage: the tests failed")
        return 1
    report = subprocess.run(
        [sys.executable, "-m", "coverage", "json", f"--data-file={data_file}", "-o", "-"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    doc = json.loads(report.stdout)
    totals = doc["totals"]
    files = sorted(
        (
            (Path(name).as_posix(), round(f["summary"]["percent_covered"], 1), f["summary"]["missing_lines"])
            for name, f in doc["files"].items()
        ),
        key=lambda x: x[1],
    )
    out = {
        "provenance": {
            "run": "coverage.py over the offline test suite (network blocked, keys stripped); scripts/ not measured",
            "note": "Line coverage of le_dispatch/ and infra/agentcore/runtime/; the claim pins a floor, not a value.",
        },
        "percent": round(totals["percent_covered"], 1),
        "statements": totals["num_statements"],
        "missed": totals["missing_lines"],
        "files": len(files),
        "least_covered": [{"file": n, "percent": p, "missing_lines": m} for n, p, m in files[:5]],
    }
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    data_file.unlink(missing_ok=True)
    print(
        f"coverage: {out['percent']}% of {out['statements']} statements ({out['missed']} missed, {out['files']} files)"
    )
    for row in out["least_covered"]:
        print(f"  {row['file']:<48} {row['percent']:>5}%  ({row['missing_lines']} lines missing)")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
