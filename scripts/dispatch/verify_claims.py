"""make verify: every cited number comes from results/ and holds.

python scripts/verify_claims.py           # every row printed with its actual value; exit 1 if any does not hold
python scripts/verify_claims.py --badge   # also write results/badges/claims.json (shields.io endpoint)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.claims import CLAIMS, RESULTS, verify_all  # noqa: E402

BADGE = RESULTS / "badges" / "claims.json"


def write_badge(verified: int, total: int, path: Path = BADGE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    badge = {
        "schemaVersion": 1,
        "label": "claims verified by CI",
        "message": f"{verified}/{total}",
        "color": "brightgreen" if verified == total else "red",
    }
    path.write_text(json.dumps(badge, indent=2) + "\n")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rows = verify_all()
    bad = 0
    for claim, ok, actual in rows:
        mark = "ok " if ok else "BAD"
        print(f"{mark} {claim.id:<28} {claim.path} {claim.op} {claim.expected!r} (actual {actual!r})")
        bad += 0 if ok else 1
    print(f"claims verified: {len(rows) - bad}/{len(CLAIMS)}")
    if "--badge" in argv:
        write_badge(len(rows) - bad, len(CLAIMS))
        print(f"wrote {BADGE}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
