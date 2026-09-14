"""make evidence: write an evidence packet for one run (JSON plus markdown with a sequence diagram).

python scripts/evidence_packet.py                       # misbehaving model, daytime: every gate fires
python scripts/evidence_packet.py --after-dark --answer yes   # the human moment, resumed
python scripts/evidence_packet.py --after-dark --answer no    # declined: plan held on file
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo_one import misbehaving_script  # noqa: E402

from le_dispatch import tracing  # noqa: E402
from le_dispatch.evidence import build_packet, render_markdown  # noqa: E402
from le_dispatch.gates import build_agent  # noqa: E402
from le_dispatch.interfaces import Trip, fixture_policy  # noqa: E402
from le_dispatch.interrupts import DecisionMemory, Inbox, build_decision_run  # noqa: E402
from le_dispatch.messages import composed_plan  # noqa: E402
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "evidence"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--after-dark", action="store_true")
    ap.add_argument("--answer", choices=("yes", "no"), default="yes")
    ap.add_argument("--origin", default="DELN")
    ap.add_argument("--destination", default="EMBR")
    ap.add_argument("--elevator", default="DELN-E1")
    ap.add_argument("--note", default=None, help="the rider's own words, read into constraints before the run")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args(argv)

    exporter = tracing.memory_exporter()
    exporter.clear()
    kb, policy = fixture_policy()
    note = None
    if args.note:  # the learner stand-in reads the note by its words, the way the runtime's model would
        from le_dispatch.bedrock_wire import wired_learner_model
        from le_dispatch.note import constrained, read_note

        kinds, how = read_note(wired_learner_model(), args.note)
        policy = constrained(policy, kinds)
        note = {"text": args.note, "constraints": kinds, "read_by": how}
    trip = Trip("rider-demo", args.origin, args.destination, (args.elevator,), after_dark=args.after_dark)
    decision = policy(trip)
    if not decision.affected:
        print("that trip is not affected by that elevator; nothing to show")
        return 1

    if args.after_dark:
        tmp = Path(tempfile.mkdtemp(prefix="le-evidence-"))
        d = decision
        script = [tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1")]
        script.append(plan_call(composed_plan(d, "send" if args.answer == "yes" else "hold"), "p1"))
        run = build_decision_run(
            ScriptedModel(script), kb, policy, trip, inbox=Inbox(tmp / "inbox.json"), memory=DecisionMemory()
        )
        run.start()
        out = run.resume(args.answer == "yes")
        bundle = run.bundle
        events = list(bundle.hook.events) + list(bundle.gate.events) + list(run.handler.events)
        plan = out.plan.model_dump() if out.plan else None
        card, answer = out.card, args.answer == "yes"
        name = f"{args.elevator}-after-dark-{args.answer}"
    else:
        bundle = build_agent(ScriptedModel(misbehaving_script(policy, trip)), kb, policy, trip)
        result = bundle.agent("Plan my trip.")
        events = list(bundle.hook.events) + list(bundle.gate.events)
        plan = result.structured_output.model_dump() if result.structured_output else None
        card, answer = None, None
        name = f"{args.elevator}-note" if args.note else f"{args.elevator}-daytime"

    events.sort(key=lambda e: e.seq)  # as they happened
    trace_events = tracing.collect_events(exporter)

    packet = build_packet(
        trip=trip,
        decision=decision,
        bundle=bundle,
        events=events,
        plan=plan,
        card=card,
        answer=answer,
        trace_events=trace_events,
        note=note,
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(packet, indent=2) + "\n")
    (out_dir / f"{name}.md").write_text(render_markdown(packet))
    print(f"wrote {out_dir / name}.json and .md")
    print(render_markdown(packet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
