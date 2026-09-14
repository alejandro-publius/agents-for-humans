"""The per-run cap wrapper: request-local folding of adjacent user turns (Bedrock requires alternating roles)."""

from __future__ import annotations

from le_dispatch.budget import BudgetedModel, merge_adjacent_user_turns
from le_dispatch.gates import build_agent, deliver
from le_dispatch.interfaces import Trip
from le_dispatch.messages import composed_plan
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call

TRIP = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=("DELN-E1",))


def _u(*texts: str) -> dict:
    return {"role": "user", "content": [{"text": t} for t in texts]}


def _tr(tool_use_id: str = "t") -> dict:
    return {"role": "user", "content": [{"toolResult": {"toolUseId": tool_use_id, "content": [], "status": "success"}}]}


def _a(text: str = "ok") -> dict:
    return {"role": "assistant", "content": [{"text": text}]}


def test_adjacent_user_text_turns_fold_into_one_and_nothing_else_changes():
    assert merge_adjacent_user_turns([_u("a"), _u("b"), _u("c")]) == [_u("a", "b", "c")]
    assert merge_adjacent_user_turns([_u("a"), _a(), _u("b")]) == [_u("a"), _a(), _u("b")]
    # a tool-result turn is never folded into (the SDK's own separator handles it) and never folded
    assert merge_adjacent_user_turns([_tr(), _u("guide")]) == [_tr(), _u("guide")]
    assert merge_adjacent_user_turns([_u("guide"), _tr()]) == [_u("guide"), _tr()]
    assert merge_adjacent_user_turns([_tr(), _u("g1"), _u("g2")]) == [_tr(), _u("g1", "g2")]
    assert merge_adjacent_user_turns([_a("x"), _a("y")]) == [_a("x"), _a("y")]
    assert merge_adjacent_user_turns("not a list") == "not a list"
    original = [_u("a"), _u("b")]
    merge_adjacent_user_turns(original)
    assert original == [_u("a"), _u("b")]  # the input is not mutated


def test_after_two_guides_the_model_never_sees_two_adjacent_user_turns(fixture_stack):
    """Two rejected Plans in a row: the SDK appends two user turns; the wrapped model receives one,
    and agent.messages (what a session manager persists) is untouched."""
    kb, policy = fixture_stack
    d = policy(TRIP)
    good = composed_plan(d)
    seen: list[list[str]] = []

    class Recording(ScriptedModel):
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            seen.append([m["role"] + ("/tr" if any("toolResult" in b for b in m["content"]) else "") for m in messages])
            async for ev in super().stream(messages, tool_specs, system_prompt, **kwargs):
                yield ev

    model = Recording(
        [
            tool_call("draft_plan", {"station": "DELN", "elevator": "DELN-E1", "option": d.top_option}, "t"),
            plan_call({**good, "added_minutes": 1}, "p1"),
            plan_call({**good, "added_minutes": 2}, "p2"),
            plan_call(good, "p3"),
        ]
    )
    bundle = build_agent(model, kb, policy, TRIP)
    out = deliver(bundle)
    assert out.composed_by == "model" and model.calls == 4
    for roles in seen:  # no two adjacent user turns ever reach the model, tool result or text
        pairs = zip(roles, roles[1:], strict=False)
        assert not any(a.startswith("user") and b.startswith("user") for a, b in pairs), roles
    # prompt, draft call, tool result, the neutral separator, the folded guides
    assert seen[-1] == ["user", "assistant", "user/tr", "assistant", "user"]
    persisted = [m["role"] for m in bundle.agent.messages]
    assert persisted[:5] == ["user", "assistant", "user", "user", "user"]  # the SDK's own history, untouched


def test_wrapper_passes_the_folded_messages_positionally_and_by_keyword():
    class Capture(ScriptedModel):
        got = None

        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            type(self).got = messages
            async for ev in super().stream(messages, tool_specs, system_prompt, **kwargs):
                yield ev

    import asyncio

    from le_dispatch.scripted_model import text_turn

    async def drain(gen):
        async for _ in gen:
            pass

    m = BudgetedModel(Capture([text_turn("x")]), cap=2)
    asyncio.run(drain(m.stream([_u("a"), _u("b")], None, None)))
    assert Capture.got == [_u("a", "b")]


def test_fuzz_every_conversation_strands_can_leave_is_sendable_after_the_passes():
    """Random conversations in the shapes Strands produces (a prompt; tool calls with their results; text
    replies; guide turns appended after a discarded reply, any number in a row): after the two passes every
    one satisfies the Converse rules, and nothing the model should see is lost or reordered."""
    import random

    from le_dispatch.bedrock_wire import converse_rule_violation
    from le_dispatch.budget import SEPARATOR_TEXT, sendable_turns

    rng = random.Random(20260913)
    for n in range(1500):
        conv = [_u("prompt")]
        k = 0
        for _ in range(rng.randint(0, 8)):
            kind = rng.choice(("tool", "text", "guide", "guide"))
            if conv[-1]["role"] == "assistant":
                kind = "guide"  # a model reply is followed by a user turn or the end, never by another reply
            if kind == "tool":
                k += 1
                conv.append(
                    {"role": "assistant", "content": [{"toolUse": {"toolUseId": f"t{k}", "name": "x", "input": {}}}]}
                )
                conv.append(_tr(f"t{k}"))
            elif kind == "text":
                conv.append(_a(f"reply {k}"))
            else:
                conv.append(_u(f"guide {k}"))
        sent = sendable_turns(conv)
        assert converse_rule_violation({"messages": sent, "toolConfig": {}}) is None, (n, conv, sent)
        texts = [b["text"] for m in conv for b in m["content"] if "text" in b]
        kept = [b["text"] for m in sent for b in m["content"] if "text" in b and b["text"] != SEPARATOR_TEXT]
        assert kept == texts, (n, conv, sent)
        results = [b["toolResult"]["toolUseId"] for m in conv for b in m["content"] if "toolResult" in b]
        assert [b["toolResult"]["toolUseId"] for m in sent for b in m["content"] if "toolResult" in b] == results
        assert conv == conv  # the input is not mutated: the same object compared before and after
