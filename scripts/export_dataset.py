"""make dataset: export the public CSV from an outage archive.

python scripts/export_dataset.py                      # fixture archive (built on demand)
python scripts/export_dataset.py --archive data/archive/outages.sqlite --query-file my_query.sql   # laptop
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.dataset_export import (  # noqa: E402
    DEFAULT_QUERY,
    FIXTURE_ARCHIVE,
    PUBLIC_DIR,
    ArchiveAdapter,
    build_fixture_archive,
    export,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(FIXTURE_ARCHIVE), help="sqlite archive; default builds the fixture")
    ap.add_argument("--query-file", default=None, help="SQL returning the documented columns for the real archive")
    ap.add_argument("--out", default=str(PUBLIC_DIR))
    args = ap.parse_args(argv)
    archive = Path(args.archive)
    if archive == FIXTURE_ARCHIVE and not archive.exists():
        build_fixture_archive(archive)
        print(f"built fixture archive {archive}")
    query = Path(args.query_file).read_text() if args.query_file else DEFAULT_QUERY
    meta = export(ArchiveAdapter(archive, query), Path(args.out))
    print(f"wrote {Path(args.out) / meta['file']} ({meta['rows']} rows, {meta['start']} to {meta['end']})")
    print(f"wrote {Path(args.out) / 'README.md'} and {meta['file']}.meta.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
