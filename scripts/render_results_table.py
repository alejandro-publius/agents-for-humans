"""make results-table: render the README policy-agreement table from results/policy_agreement.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.eval_live import RESULTS_PATH, load_entries, render_readme_section  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(RESULTS_PATH))
    args = ap.parse_args(argv)
    print(render_readme_section(load_entries(Path(args.results))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
