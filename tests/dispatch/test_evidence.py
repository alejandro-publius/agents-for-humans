"""F13: evidence packets are complete, deterministic, and current."""

from __future__ import annotations

import json
import subprocess
import sys

from le_dispatch.evidence import render_markdown, sequence_diagram
from le_dispatch.interfaces import ROOT  # the repo root in either layout (tests/ or tests/dispatch/)

EVIDENCE = ROOT / "docs" / "evidence"


def test_checked_in_packets_regenerate_byte_identical(tmp_path):
    """No timestamps, no randomness: a rerun on the same inputs is the same file."""
    script = ROOT / "scripts" / "evidence_packet.py"
    for args, name in (
        ([], "DELN-E1-daytime"),
        (["--after-dark", "--answer", "yes"], "DELN-E1-after-dark-yes"),
        (["--after-dark", "--answer", "no"], "DELN-E1-after-dark-no"),
        (["--note", "no ramps today, I am pushing a stroller"], "DELN-E1-note"),
    ):
        subprocess.run([sys.executable, str(script), *args, "--out", str(tmp_path)], check=True, capture_output=True)
        for ext in ("json", "md"):
            assert (tmp_path / f"{name}.{ext}").read_text() == (EVIDENCE / f"{name}.{ext}").read_text(), name


def test_packet_contents_and_diagram():
    daytime = json.loads((EVIDENCE / "DELN-E1-daytime.json").read_text())
    kinds = [e["kind"] for e in daytime["gate_events"]]
    assert kinds == [
        "hook.cancel_tool",
        "steering.guide",
        "tool.ran",  # the accepted call is on the packet too, so every model action is drawn
        "steering.guide_after_model",
        "steering.proceed_after_model",
    ]
    diagram = (EVIDENCE / "DELN-E1-daytime.md").read_text()
    assert "M->>T: draft_plan(station='DELN', elevator='DELN-E1', option='alternate_elevator')" in diagram
    assert daytime["final_plan"]["option"] == daytime["decision"]["top_option"]
    assert daytime["provenance"]["claimable"] is False
    assert daytime["counts"]["model_calls"] == 5
    diagram = sequence_diagram(daytime)
    assert diagram.startswith("sequenceDiagram") and "cancelled: not in the knowledge base" in diagram
    assert "plan delivered" in diagram
    md = render_markdown(daytime)
    for heading in (
        "## Trip and outage",
        "## What code decided",
        "## What the model tried",
        "## What reached the rider",
    ):
        assert heading in md

    asked = json.loads((EVIDENCE / "DELN-E1-after-dark-yes.json").read_text())
    assert asked["decision_card"]["question"].endswith("Send this plan now?")
    assert asked["rider_answer"] is True and asked["final_plan"]["status"] == "send"
    assert [e["kind"] for e in asked["gate_events"]][:2] == ["interrupt.raised", "interrupt.resumed"]

    held = json.loads((EVIDENCE / "DELN-E1-after-dark-no.json").read_text())
    assert held["rider_answer"] is False and held["final_plan"]["status"] == "hold"
    assert held["final_plan"]["option"] == held["decision"]["top_option"]  # BART's plan stays on file


def test_every_outcome_and_packet_states_what_the_decision_cost(fixture_stack):
    """Model calls, tokens and cycles from Strands' own metrics, on the delivery outcome and in the packet;
    the scripted model reports one input and one output token per call, so the arithmetic is checkable."""
    from le_dispatch.evidence import build_packet
    from le_dispatch.gates import build_agent, deliver, run_usage
    from le_dispatch.interfaces import Trip
    from le_dispatch.messages import composed_plan
    from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call

    kb, policy = fixture_stack
    trip = Trip("r", "DELN", "EMBR", ("DELN-E1",))
    d = policy(trip)
    good = composed_plan(d)
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t"),
            plan_call({**good, "added_minutes": 1}, "p1"),
            plan_call(good, "p2"),
        ]
    )
    bundle = build_agent(model, kb, policy, trip)
    out = deliver(bundle)
    assert out.composed_by == "model"
    assert out.usage == {"model_calls": 3, "input_tokens": 3, "output_tokens": 3, "total_tokens": 6, "cycles": 2}
    assert run_usage(bundle) == out.usage
    events = sorted(list(bundle.hook.events) + list(bundle.gate.events), key=lambda e: e.seq)
    packet = build_packet(trip=trip, decision=d, bundle=bundle, events=events, plan=out.plan)
    assert packet["cost"] == out.usage
    assert "Cost of this decision: 3 model call(s), 3 input and 3 output tokens (6 total)" in render_markdown(packet)
    # a run that never complies still reports what it cost
    stubborn = ScriptedModel(
        [tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t")]
        + [plan_call({**good, "added_minutes": 1}, f"p{k}") for k in range(30)]
    )
    out2 = deliver(build_agent(stubborn, kb, policy, trip))
    assert out2.composed_by == "code" and out2.usage["model_calls"] == 24 and out2.usage["total_tokens"] == 48


def test_the_note_packet_says_what_the_rider_wrote_and_what_moved():
    """The fourth packet: the rider's words, what the model read them as, that code applied them as
    feasibility only, the ruled-out option infeasible in the table, the plan on BART's next option."""
    import json

    packet = json.loads((EVIDENCE / "DELN-E1-note.json").read_text())
    assert packet["note"] == {
        "text": "no ramps today, I am pushing a stroller",
        "constraints": ["avoid_ramps"],
        "read_by": "model",
    }
    d = packet["decision"]
    assert d["note_constraints"] == ["avoid_ramps"] and d["note_set_aside"] is False and d["top_option"] == "transit"
    assert [o["feasible"] for o in d["ranked"]] == [False, True]
    assert packet["final_plan"]["option"] == "transit" and packet["final_plan"]["added_minutes"] == 20
    text = (EVIDENCE / "DELN-E1-note.md").read_text()
    assert "## The rider's own words" in text and "avoid_ramps ruled out" in text and "feasibility only" in text
