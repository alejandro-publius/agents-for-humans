"""make impact: what riders faced, from the agency's own feed (le_dispatch/impact.py).

    python scripts/impact.py                                   # the fixture archive (built on demand)
    python scripts/impact.py --archive data/archive/outages.sqlite --query-file my_query.sql   # laptop

Writes results/outage_week.json and prints the summary. Nothing is a result until the laptop runs it on the
real archive.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.dataset_export import FIXTURE_ARCHIVE, build_fixture_archive  # noqa: E402
from le_dispatch.impact import RESULTS_PATH, render, run, write  # noqa: E402
from le_dispatch.interfaces import load_kb, source_label  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(FIXTURE_ARCHIVE), help="sqlite archive; default builds the fixture")
    ap.add_argument("--query-file", default=None, help="SQL returning the documented columns for the real archive")
    ap.add_argument("--kb", default=None, help="KB export JSON (LE_KB_EXPORT, else the fixture)")
    ap.add_argument("--out", default=str(RESULTS_PATH))
    args = ap.parse_args(argv)
    archive = Path(args.archive)
    if archive == FIXTURE_ARCHIVE and not archive.exists():
        build_fixture_archive(archive)
    query = Path(args.query_file).read_text() if args.query_file else None
    doc = run(archive, load_kb(args.kb), query)
    out = Path(args.out)
    written = write(doc, out)
    print(render(doc))
    if written:
        print(f"wrote {out} ({source_label()}, archive: {doc['provenance']['archive']})")
    else:
        print(f"left {out} as committed: it came from a real archive and this run read the fixture one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
