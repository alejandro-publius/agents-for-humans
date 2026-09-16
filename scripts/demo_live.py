"""make demo-live: one case on a live Bedrock model through the full stack, with an evidence packet. Laptop only.

    python scripts/demo_live.py                     # dry run: prints what it would call, calls nothing
    python scripts/demo_live.py --yes               # laptop: one run, a few model calls, writes docs/evidence/live-*.md
    python scripts/demo_live.py --stand-in          # the same path with a stand-in client; the packet goes to /tmp

The point for the video: a real model proposes, the same gates decide,
and the packet shows every attempt. Provenance says "live model <id>";
the packet is still not a claimed result until the laptop commits it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch import (
    live,  # noqa: E402
    tracing,  # noqa: E402
)
from le_dispatch.eval_live import credentials_present, load_models  # noqa: E402
from le_dispatch.evidence import build_packet, render_markdown  # noqa: E402
from le_dispatch.gates import build_agent, deliver  # noqa: E402
from le_dispatch.interfaces import Trip, fixture_policy, source_label  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "evidence"


def bedrock_model(model_id: str, region: str):
    """The live model on the live client configuration (le_dispatch/live.py): botocore's own retries off,
    a read timeout; Strands' bounded strategy goes on the agent."""
    return live.model(model_id, region)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="actually call Bedrock (laptop)")
    ap.add_argument("--model", default=None, help="model id; default: the first entry of evals/live_models.json")
    ap.add_argument("--origin", default="DELN")
    ap.add_argument("--destination", default="EMBR")
    ap.add_argument("--elevator", default="DELN-E1")
    ap.add_argument("--note", default=None, help="the rider's own words for today, read into constraints first")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument(
        "--stand-in",
        action="store_true",
        help="the dress rehearsal: a real BedrockModel whose client is a stand-in that reads the conversation; "
        "no credentials, nothing called, the packet written under the temp directory, never a result",
    )
    args = ap.parse_args(argv)

    cfg = load_models()
    model_id = args.model or cfg["models"][0].model_id
    region = cfg["region"]
    kb, policy = fixture_policy()  # the laptop swaps in the real KB and policy engine
    trip = Trip("rider-live", args.origin, args.destination, (args.elevator,))
    decision = policy(trip)
    prompt = (
        f"Plan my trip from {trip.origin} to {trip.destination}. Elevator {args.elevator} at "
        f"{trip.origin} is out. Use draft_plan, then return the Plan with one of the approved sentences."
    )
    print(f"model: {model_id} ({region}); trip {trip.origin} to {trip.destination}, outage {args.elevator}")
    minutes = decision.minutes_for(decision.top_option)
    print(f"policy engine: {decision.kind}, top option {decision.top_option}, minutes {minutes}")
    if args.stand_in:
        from le_dispatch.bedrock_wire import wired_learner_model

        model = wired_learner_model(model_id, region)
        if args.out == str(OUT_DIR):
            args.out = str(Path(tempfile.gettempdir()) / "le-demo-live-stand-in")
        print("stand-in: the real BedrockModel, its client a stand-in that reads the conversation; nothing called")
    elif not args.yes or not credentials_present():
        print(
            "dry run: would build the gated agent on BedrockModel, run deliver() with the per-run cap, "
            "and write docs/evidence/live-<model>.md; nothing called (--stand-in runs the same path offline)"
        )
        return 0
    else:
        model = bedrock_model(model_id, region)  # laptop only

    exporter = tracing.memory_exporter()
    exporter.clear()
    if args.note:  # the rider's own words first: one structured-output call, applied as feasibility only
        from le_dispatch.note import constrained, plain_words, read_note

        kinds, how = read_note(model, args.note)
        policy = constrained(policy, kinds)
        decision = policy(trip)
        read = plain_words(kinds) or "nothing ruled out"
        print(f'note: "{args.note}" read as {read} ({how}); top option now {decision.top_option}')
    bundle = build_agent(model, kb, policy, trip, retry_strategy=live.retry_strategy())
    out = deliver(bundle, prompt)
    events = sorted(list(bundle.hook.events) + list(bundle.gate.events), key=lambda e: e.seq)
    packet = build_packet(
        trip=trip,
        decision=decision,
        bundle=bundle,
        events=events,
        plan=out.plan,
        trace_events=tracing.collect_events(exporter),
        provenance=(
            f"stand-in client for {model_id} (nothing called), {source_label()}; composed_by={out.composed_by}"
            if args.stand_in
            else f"live model {model_id} in {region}, {source_label()}; composed_by={out.composed_by}"
        ),
    )
    packet["delivery"] = {"composed_by": out.composed_by, "stop_reason": out.stop_reason, "reason": out.reason}
    name = ("stand-in-" if args.stand_in else "live-") + model_id.replace(":", "-").replace(".", "-").replace("/", "-")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(packet, indent=2) + "\n")
    (out_dir / f"{name}.md").write_text(render_markdown(packet))
    print(render_markdown(packet))
    print(f"wrote {out_dir / name}.md (model calls: {getattr(bundle.agent.model, 'calls', '?')})")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
    raise SystemExit(main())
