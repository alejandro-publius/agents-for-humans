"""The rider's inbox from the command line (what the app does with taps).

python scripts/inbox.py list [--inbox path]
python scripts/inbox.py answer <case_key> yes|no [--inbox path]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.interrupts import Inbox  # noqa: E402

DEFAULT = Path(__file__).resolve().parent.parent / "data" / "inbox.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", default=str(DEFAULT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    ans = sub.add_parser("answer")
    ans.add_argument("case_key")
    ans.add_argument("answer", choices=("yes", "no"))
    args = ap.parse_args(argv)

    inbox = Inbox(args.inbox)
    if args.cmd == "list":
        pending = inbox.pending()
        if not pending:
            print("inbox: nothing pending")
            return 0
        for c in pending:
            print(f"[{c.case_key}] {c.question}")
            print(f"    option {c.option}, added minutes {c.added_minutes}, source {c.source_url}")
            for r in c.rejected:
                print(f"    rejected {r['label']}: {r['reason']}")
        return 0
    card = inbox.get(args.case_key)
    if card is None:
        print(f"no card for {args.case_key}")
        return 1
    inbox.answer(args.case_key, args.answer == "yes")
    print(f"answered {args.case_key}: {args.answer}. The next poll resumes the run from the session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
