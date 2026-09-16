"""make wire: the live path through Strands' real Bedrock adapter, offline.

Writes docs/evidence/bedrock-request.json (the first request Bedrock would receive for the fixture trip),
docs/evidence/bedrock-wire.md (every request of seven scenarios, what the stand-in did with it, the outcome)
and results/bedrock_wire.json (the counts the claims table checks). Nothing is sent: the boto3 client is
replaced by a stand-in that enforces the Converse rules and replays scripted chunks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.bedrock_wire import (  # noqa: E402
    DEFAULT_MODEL_ID,
    first_request,
    render_markdown,
    results_doc,
    run_all,
)
from le_dispatch.interfaces import Trip, fixture_policy, source_label, write_results_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence"
RESULTS = ROOT / "results" / "bedrock_wire.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", default=DEFAULT_MODEL_ID, help="the model id on the request (no call is made)")
    ap.add_argument("--origin", default="DELN")
    ap.add_argument("--destination", default="EMBR")
    ap.add_argument("--elevator", default="DELN-E1")
    ap.add_argument("--out", default=str(EVIDENCE))
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args(argv)

    kb, policy = fixture_policy()
    trip = Trip("rider-wire", args.origin, args.destination, (args.elevator,))
    if not policy(trip).affected:
        print("that trip is not affected by that elevator; nothing to send")
        return 1
    runs = run_all(kb, policy, trip, model_id=args.model_id)
    doc = results_doc(runs, args.model_id)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bedrock-request.json").write_text(json.dumps(first_request(runs), indent=2, sort_keys=True) + "\n")
    (out / "bedrock-wire.md").write_text(render_markdown(runs, args.model_id))
    results = Path(args.results)
    written = write_results_json(results, doc)

    for name, s in doc["scenarios"].items():
        print(
            f"{name:<20} composed by {s['composed_by']:<5} calls {s['model_calls']:>2} requests {s['requests']:>2} "
            f"rejected {s['rejected_by_converse_rules']}"
        )
    files = f"{out / 'bedrock-request.json'}, {out / 'bedrock-wire.md'}" + (f", {results}" if written else "")
    print(f"wrote {files} ({source_label()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
