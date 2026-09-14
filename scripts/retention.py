"""make retention: the retention rule for what the agent keeps about a rider. Dry run unless --yes.

    python scripts/retention.py --data-dir /path/to/data --days 30            # what would go
    python scripts/retention.py --data-dir /path/to/data --days 30 --yes      # drop it

Closed decision cards (answered or withdrawn) older than --days are dropped
from the inbox; open cards never are. Evidence packets under --data-dir
older than --days are listed (and removed with --yes). Session files,
decision mirrors and the outage archive are the owner's: this script never
touches them, and it never reads data/archive/.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.interrupts import Inbox  # noqa: E402


def stale_packets(data_dir: Path, days: int, now: datetime) -> list[Path]:
    cutoff = now.timestamp() - days * 86400
    packets = data_dir / "evidence"
    if not packets.is_dir():
        return []
    return sorted(p for p in packets.iterdir() if p.is_file() and p.stat().st_mtime < cutoff)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="the runtime data directory (inbox.json, evidence/)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--yes", action="store_true", help="apply; default is a dry run")
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir).expanduser()
    now = datetime.now(UTC)
    inbox = Inbox(data_dir / "inbox.json")
    would = inbox.purge(older_than_days=args.days, now=now) if args.yes else _preview(inbox, args.days, now)
    packets = stale_packets(data_dir, args.days, now)
    verb = "dropped" if args.yes else "would drop"
    print(f"retention ({args.days} days, {'applied' if args.yes else 'dry run'}): {verb} {len(would)} closed card(s)")
    for key in would:
        print(f"  card {key}")
    print(f"  {verb} {len(packets)} evidence packet(s) older than {args.days} days under {data_dir / 'evidence'}")
    for p in packets:
        print(f"  packet {p.name}")
        if args.yes:
            p.unlink()
    print("open cards are never dropped; sessions, decision mirrors and the archive are not touched")
    return 0


def _preview(inbox: Inbox, days: int, now: datetime) -> list[str]:
    cutoff = now.timestamp() - days * 86400
    out = []
    for c in inbox._load():
        closed_at = c.get("answered_at") or c.get("withdrawn_at")
        if c.get("answer") is None and not c.get("withdrawn_at"):
            continue
        if closed_at and datetime.fromisoformat(closed_at).timestamp() < cutoff:
            out.append(c["case_key"])
    return out


if __name__ == "__main__":
    raise SystemExit(main())
