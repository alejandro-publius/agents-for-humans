"""F1: two-stage enforcement, proven end to end with a scripted model.

The scripted model misbehaves in every way a live model could, in order:
unknown elevator (hook cancels), wrong option (Guide before the tool),
correct draft, then a wrong final Plan (Guide after the model), then a
correct Plan (Proceed). Exactly one of each gate event, zero network calls.
"""

from __future__ import annotations

import pytest
from le_dispatch import tracing
from le_dispatch.gates import build_agent, deliver, extract_plan
from le_dispatch.interfaces import Trip
from le_dispatch.messages import composed_plan
from le_dispatch.scripted_model import ScriptedModel, plan_call, text_turn, tool_call

TRIP = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=("DELN-E1",))


def good_plan(policy, trip=TRIP, **overrides):
    d = policy(trip)
    plan = composed_plan(d)
    del plan["status"]
    plan.update(overrides)
    return plan


def test_fixture_policy_top_option_is_bart_order(fixture_stack):
    kb, policy = fixture_stack
    d = policy(TRIP)
    assert d.affected and d.kind == "cannot_enter" and d.station == "DELN" and d.elevator == "DELN-E1"
    labels = [o.label for o in d.ranked]
    assert labels == sorted(labels, key=kb.rank)
    assert d.top_option == labels[0]


def test_two_stage_gate_corrects_every_mistake_once(fixture_stack):
    kb, policy = fixture_stack
    d = policy(TRIP)
    wrong_option = next(o.label for o in d.ranked if o.label != d.top_option)
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E9", "option": d.top_option}, "t1"),
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": wrong_option}, "t2"),
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t3"),
            plan_call(good_plan(policy, option=wrong_option, added_minutes=99), "p1"),
            plan_call(good_plan(policy), "p2"),
        ]
    )
    bundle = build_agent(model, kb, policy, TRIP)
    result = bundle.agent("Plan my trip.")

    assert bundle.hook.cancels == 1
    assert bundle.gate.count(tracing.GUIDE_BEFORE) == 1
    assert bundle.gate.count(tracing.GUIDE_AFTER) == 1
    assert bundle.gate.count(tracing.PROCEED_AFTER) == 1
    assert result.structured_output is not None
    assert result.structured_output.option == d.top_option
    assert result.structured_output.added_minutes == d.minutes_for(d.top_option)
    # the rejected plan never entered the conversation
    plans = [
        b["toolUse"]["input"]
        for m in bundle.agent.messages
        for b in m["content"]
        if "toolUse" in b and b["toolUse"]["name"] == "Plan"
    ]
    assert plans == [good_plan(policy)]
    assert model.calls == 5


def test_correct_plan_passes_with_one_proceed(fixture_stack):
    kb, policy = fixture_stack
    d = policy(TRIP)
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t1"),
            plan_call(good_plan(policy), "p1"),
        ]
    )
    bundle = build_agent(model, kb, policy, TRIP)
    result = bundle.agent("Plan my trip.")
    assert bundle.hook.cancels == 0
    assert bundle.gate.count(tracing.GUIDE_BEFORE) == 0
    assert bundle.gate.count(tracing.GUIDE_AFTER) == 0
    assert bundle.gate.count(tracing.PROCEED_AFTER) == 1
    assert result.structured_output.model_dump() == {**good_plan(policy), "status": "send"}


def test_after_model_gate_rejects_invented_minutes_and_foreign_station(fixture_stack):
    kb, policy = fixture_stack
    bundle = build_agent(ScriptedModel([]), kb, policy, TRIP)
    gate = bundle.gate
    assert gate.check_plan(good_plan(policy)) == []
    assert any("added_minutes" in p for p in gate.check_plan(good_plan(policy, added_minutes=3)))
    assert any("not in the knowledge base" in p for p in gate.check_plan(good_plan(policy, station="XXXX")))
    assert any("not the affected station" in p for p in gate.check_plan(good_plan(policy, station="EMBR")))
    assert any("top feasible option" in p for p in gate.check_plan(good_plan(policy, option="transit")))


def test_no_steering_ablation_lets_wrong_option_through(fixture_stack):
    """Plumbing proof only: with steering off, the hook still blocks unknown
    stations but a wrong option reaches the rider. Never cite this as a result."""
    kb, policy = fixture_stack
    d = policy(TRIP)
    wrong_option = next(o.label for o in d.ranked if o.label != d.top_option)
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": wrong_option}, "t1"),
            plan_call(good_plan(policy, option=wrong_option, added_minutes=d.minutes_for(wrong_option)), "p1"),
        ]
    )
    bundle = build_agent(model, kb, policy, TRIP, steering=False)
    result = bundle.agent("Plan my trip.")
    assert bundle.gate is None
    assert result.structured_output.option == wrong_option


def test_trace_has_after_model_span_event(fixture_stack):
    kb, policy = fixture_stack
    exporter = tracing.memory_exporter()
    exporter.clear()
    d = policy(TRIP)
    wrong_option = next(o.label for o in d.ranked if o.label != d.top_option)
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t1"),
            plan_call(good_plan(policy, option=wrong_option), "p1"),
            plan_call(good_plan(policy), "p2"),
        ]
    )
    build_agent(model, kb, policy, TRIP).agent("Plan my trip.")
    events = tracing.collect_events(exporter)
    names = [e["event"] for e in events]
    assert tracing.GUIDE_AFTER in names and tracing.PROCEED_AFTER in names
    rendered = tracing.render_events(events)
    assert "steering.guide_after_model" in rendered


def test_extract_plan_falls_back_to_json_text():
    msg = {"role": "assistant", "content": [{"text": 'Here: {"station": "DELN", "option": "transit"} done'}]}
    assert extract_plan(msg, "Plan") == {"station": "DELN", "option": "transit"}
    assert extract_plan({"role": "assistant", "content": [{"text": "no plan"}]}, "Plan") is None


def test_script_exhaustion_is_loud(fixture_stack):
    """An exhausted script ends the turn; Strands forces the structured output
    tool once, then raises. Runaway loops fail loudly, never hang."""
    kb, policy = fixture_stack
    assert text_turn("x")[4]["messageStop"]["stopReason"] == "end_turn"
    bundle = build_agent(ScriptedModel([]), kb, policy, TRIP, steering=False)
    with pytest.raises(Exception) as excinfo:
        bundle.agent("Plan my trip.")
    assert "structured output" in str(excinfo.value).lower()


def test_gates_fail_closed_on_internal_error(fixture_stack, monkeypatch):
    """An exception inside a gate is a Guide, never a Proceed."""
    import asyncio

    from le_dispatch.gates import PlanGateHandler
    from strands.vended_plugins.steering.core.action import Guide

    kb, policy = fixture_stack
    gate = PlanGateHandler(kb=kb, policy=policy, trip=TRIP)

    def boom(_plan):
        raise RuntimeError("policy engine unreachable")

    monkeypatch.setattr(gate, "check_plan", boom)
    msg = {
        "role": "assistant",
        "content": [{"toolUse": {"toolUseId": "p", "name": "Plan", "input": good_plan(policy)}}],
    }
    action = asyncio.run(gate.steer_after_model(agent=None, message=msg, stop_reason="tool_use"))
    assert isinstance(action, Guide) and "gate error" in action.reason
    assert gate.count(tracing.GUIDE_AFTER) == 1

    broken_policy = lambda trip: (_ for _ in ()).throw(RuntimeError("engine down"))  # noqa: E731
    gate2 = PlanGateHandler(kb=kb, policy=broken_policy, trip=TRIP)
    tool_use = {"name": "draft_plan", "input": {"station": "DELN", "elevator": "DELN-E1", "option": "transit"}}
    action2 = asyncio.run(gate2.steer_before_tool(agent=None, tool_use=tool_use))
    assert isinstance(action2, Guide) and "refusing to proceed" in action2.reason


def test_prose_names_the_wrong_option(fixture_stack):
    from le_dispatch.gates import prose_findings

    kb, policy = fixture_stack
    assert prose_findings("Backtrack one stop and return.", kb, 4, "alternate_elevator") == [
        "rider_message names the 'backtracking' option; the plan's option is 'alternate_elevator'"
    ]
    assert prose_findings("Use the alternate elevator, about 4 minutes more.", kb, 4, "alternate_elevator") == []
    # "AC Transit" is an operator name, never flagged
    assert prose_findings("Take AC Transit from DELN; about 4 minutes more.", kb, 4, "alternate_elevator") == []


def test_unaffected_trip_is_refused(fixture_stack):
    """Affectedness is the policy engine's. A draft for an unaffected trip is
    Guided, a plan for one is rejected, and deliver() never runs the model."""
    import asyncio

    from le_dispatch.gates import PlanGateHandler, deliver
    from strands.vended_plugins.steering.core.action import Guide

    kb, policy = fixture_stack
    quiet_trip = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=())
    assert policy(quiet_trip).affected is False
    gate = PlanGateHandler(kb=kb, policy=policy, trip=quiet_trip)
    tool_use = {"name": "draft_plan", "input": {"station": "DELN", "elevator": "DELN-E1", "option": "transit"}}
    action = asyncio.run(gate.steer_before_tool(agent=None, tool_use=tool_use))
    assert isinstance(action, Guide) and "not affected" in action.reason
    problems = gate.check_plan(good_plan(policy))
    assert any("not affected" in p for p in problems)
    model = ScriptedModel([plan_call(good_plan(policy), "p1")])
    out = deliver(build_agent(model, kb, policy, quiet_trip))
    assert out.plan is None and out.composed_by == "none" and out.stop_reason == "not_affected"
    assert model.calls == 0  # nothing to send, so the model is never called


def test_forced_structured_output_is_gated_and_its_failure_is_delivered(fixture_stack):
    """A live model often answers in prose after the tool instead of calling Plan. Strands then forces the
    Plan tool in a new cycle; the after-model gate must see that forced Plan too (a wrong one is discarded
    and retried), and a model that still will not call Plan raises StructuredOutputException, which
    deliver() turns into a code-composed plan."""
    kb, policy = fixture_stack
    d = policy(TRIP)
    good = good_plan(policy)
    chatty = ScriptedModel(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t1"),
            text_turn("Here is your plan in prose: take the alternate elevator."),  # end_turn: Strands forces Plan
            plan_call({**good, "added_minutes": 1}, "p1"),  # the forced Plan, wrong: gated
            plan_call(good, "p2"),  # the retry, right
        ]
    )
    bundle = build_agent(chatty, kb, policy, TRIP)
    out = deliver(bundle)
    assert out.composed_by == "model" and out.plan["added_minutes"] == d.minutes_for(d.top_option)
    assert bundle.gate.count(tracing.GUIDE_AFTER) == 1 and bundle.gate.count(tracing.PROCEED_AFTER) == 1
    assert chatty.calls == 4

    stubborn = ScriptedModel(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t1"),
            text_turn("prose only"),
            text_turn("still prose, even when forced"),
        ]
    )
    bundle = build_agent(stubborn, kb, policy, TRIP)
    out = deliver(bundle)
    assert out.composed_by == "code" and out.stop_reason == "exception"
    assert "StructuredOutputException" in out.reason and out.plan["option"] == d.top_option


def test_delivery_rechecks_the_plan_even_if_the_gate_never_fired(fixture_stack, monkeypatch):
    """Belt and braces: if the SDK did not invoke the after-model gate (a plumbing change), the delivery
    layer runs the same checks once more and composes the plan in code rather than deliver a wrong one."""
    from le_dispatch.gates import PlanGateHandler
    from strands.vended_plugins.steering.core.action import Proceed

    kb, policy = fixture_stack
    d = policy(TRIP)
    wrong = {**good_plan(policy), "added_minutes": 1, "option": "transit"}

    async def never_fires(self, *, agent, message, stop_reason, **kwargs):
        return Proceed(reason="simulated: the after-model hook was not invoked")

    monkeypatch.setattr(PlanGateHandler, "steer_after_model", never_fires)
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t1"),
            plan_call(wrong, "p1"),
        ]
    )
    bundle = build_agent(model, kb, policy, TRIP)
    out = deliver(bundle)
    assert out.composed_by == "code" and out.stop_reason == "final_check"
    assert "final check failed" in out.reason and "option 'transit'" in out.reason
    assert out.plan["option"] == d.top_option and out.plan["added_minutes"] == d.minutes_for(d.top_option)
    assert bundle.gate.count(tracing.GUIDE_AFTER) == 0  # the gate indeed never fired; the last line held
