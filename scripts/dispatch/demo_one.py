"""make demo-one: one rider, one outage, offline, on the scripted model.

    python scripts/demo_one.py            # plain run
    python scripts/demo_one.py --trace    # also render the gate span events
    python scripts/demo_one.py --after-dark   # F2: pause for the rider, then resume (scripted answer)
    python scripts/demo_one.py --brief    # the same run as a few plain lines, for the first shot of the video

The scripted model misbehaves on purpose (unknown elevator, wrong option,
wrong final plan) so the demo shows every gate firing before the correct
plan reaches the rider. No network, no credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch import tracing  # noqa: E402
from le_dispatch.gates import build_agent  # noqa: E402
from le_dispatch.interfaces import Trip, fixture_policy  # noqa: E402
from le_dispatch.messages import composed_plan  # noqa: E402
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call  # noqa: E402


def misbehaving_script(policy, trip):
    d = policy(trip)
    wrong = next(o.label for o in d.ranked if o.label != d.top_option)
    good = composed_plan(d)
    del good["status"]
    return [
        tool_call("draft_plan", {"station": d.station, "elevator": "FAKE-E7", "option": d.top_option}, "t1"),
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": wrong}, "t2"),
        tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t3"),
        plan_call({**good, "option": wrong, "added_minutes": 1}, "p1"),
        plan_call(good, "p2"),
    ]


def brief(bundle, plan) -> str:
    """The run as the video's first shot reads it: what code decided, what the model tried, what stopped it,
    what reached the rider. Every line is from the decision, the gate events and the final plan."""
    from le_dispatch.messages import KIND_WORDS, LABEL_WORDS_PLAIN

    d = bundle.gate.decision
    where = KIND_WORDS.get(d.kind or "", d.kind or "")
    minutes = d.minutes_for(d.top_option)
    lines = [
        f"code decided: {d.spoken_station} elevator {d.elevator} is out {where}; BART's option, in BART's order: "
        f"{LABEL_WORDS_PLAIN.get(d.top_option or '', d.top_option)}, about {minutes} minutes more",
    ]
    stopped = {
        tracing.HOOK_CANCEL: "the hook cancelled it before the tool ran",
        tracing.GUIDE_BEFORE: "the steering gate before the tool sent it back with BART's order",
        tracing.GUIDE_AFTER: "the steering gate after the model threw the plan away",
    }
    events = sorted(list(bundle.hook.events) + list(bundle.gate.events), key=lambda e: e.seq)
    n = 0
    for e in events:
        if e.kind not in stopped:
            continue
        n += 1
        tried = ", ".join(
            f"{k}={v!r}" for k, v in sorted(e.detail.items()) if k in ("station", "elevator", "option", "added_minutes")
        )
        lines.append(f"the model tried ({n}): {e.tool} with {tried}")
        lines.append(f"  what stopped it: {stopped[e.kind]}")
    lines.append(
        f"what reached the rider: {plan.option} at {plan.station} ({plan.elevator}), "
        f"{plan.added_minutes} minutes more, in a sentence code composed from BART's wording:"
    )
    lines.append(f'  "{plan.rider_message}"')
    lines.append("models propose, code decides")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", action="store_true", help="render gate span events")
    ap.add_argument("--after-dark", action="store_true", help="F2: interrupt for a rider decision, then resume")
    ap.add_argument("--rider", default="rider-demo")
    ap.add_argument("--brief", action="store_true", help="what code decided, what the model tried, what stopped it")
    ap.add_argument("--note", default=None, help="the rider's own words for today (read into constraints first)")
    args = ap.parse_args(argv)

    exporter = tracing.memory_exporter() if args.trace else None
    kb, policy = fixture_policy()
    trip = Trip(
        rider_id=args.rider, origin="DELN", destination="EMBR", outages=("DELN-E1",), after_dark=args.after_dark
    )

    if args.after_dark:
        from le_dispatch.interrupts import demo_after_dark

        return demo_after_dark(kb, policy, trip, exporter)

    note_line = ""
    if args.note:
        from le_dispatch.bedrock_wire import wired_learner_model
        from le_dispatch.note import constrained, plain_words, read_note

        kinds, how = read_note(wired_learner_model(), args.note)  # the stand-in reads the note by its words
        policy = constrained(policy, kinds)
        note_line = (
            f'the rider wrote: "{args.note}"; read as: {plain_words(kinds) or "nothing ruled out"} ({how}); '
            "code applied it as feasibility only, BART's order among the rest stands"
        )
    bundle = build_agent(ScriptedModel(misbehaving_script(policy, trip)), kb, policy, trip)
    result = bundle.agent("Plan my trip.")
    if args.brief:
        if note_line:
            print(note_line)
        print(brief(bundle, result.structured_output))
        return 0
    if note_line:
        print(note_line)
    print("decision:", json.dumps(bundle.gate.decision.to_dict(), indent=1)[:400], "...")
    print("hook cancels:", bundle.hook.cancels)
    print("guide before tool:", bundle.gate.count(tracing.GUIDE_BEFORE))
    print("guide after model:", bundle.gate.count(tracing.GUIDE_AFTER))
    print("proceed after model:", bundle.gate.count(tracing.PROCEED_AFTER))
    print("final plan:", result.structured_output.model_dump_json())
    if exporter is not None:
        print("\n== gate span events ==")
        print(tracing.render_events(tracing.collect_events(exporter)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
