"""F17: the rider never receives a sentence the model wrote alone, and always receives a plan."""

from __future__ import annotations

from dataclasses import replace

from le_dispatch import tracing
from le_dispatch.gates import build_agent, deliver
from le_dispatch.interfaces import Trip
from le_dispatch.messages import (
    approval_hint,
    approved_messages,
    composed_plan,
    hold_messages,
    is_approved,
    normalize,
)
from le_dispatch.red_team import INJECTION
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call

TRIP = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=("DELN-E1",))


def test_approved_sentences_are_composed_from_the_decision_and_barts_text(fixture_stack):
    kb, policy = fixture_stack
    d = policy(TRIP)
    sentences = approved_messages(d)
    assert len(sentences) == 4 and len(set(sentences)) == 4
    option_text = next(o.reason for o in d.ranked if o.label == d.top_option)
    assert len(sentences[0]) <= 160  # the default fits a notification (one screen, no truncation)
    assert f"about {d.minutes_for(d.top_option)} minutes more" in sentences[0]
    for s in sentences[1:]:
        assert d.station in s and d.elevator in s and option_text.rstrip(".") in s
        assert f"About {d.minutes_for(d.top_option)} minutes more" in s
    for s in sentences:
        assert is_approved(s, d)
    assert is_approved("  " + sentences[0].replace(". ", ".  ") + " !", d)  # whitespace and punctuation tolerated
    assert not is_approved(sentences[0].replace("4 minutes", "40 minutes"), d)
    assert not is_approved(INJECTION, d)
    assert not is_approved("", d)
    assert normalize(None) == ""
    holds = hold_messages(d)
    assert all(is_approved(h, d, "hold") for h in holds) and not is_approved(holds[0], d, "send")
    assert sentences[0] in approval_hint(d)
    unaffected = policy(Trip("r1", "DELN", "EMBR", ()))
    assert approved_messages(unaffected) == [] and hold_messages(unaffected) == []


def test_gate_discards_own_words_and_injected_text(fixture_stack):
    kb, policy = fixture_stack
    d = policy(TRIP)
    good = composed_plan(d)
    own_words = {**good, "rider_message": "Elevator out at DELN; use the other elevator, about 4 minutes more."}
    injected = {**good, "rider_message": INJECTION}
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
            plan_call(own_words, "p1"),
            plan_call(injected, "p2"),
            plan_call(good, "p3"),
        ]
    )
    bundle = build_agent(model, kb, policy, TRIP)
    out = deliver(bundle)
    assert out.composed_by == "model" and out.plan["rider_message"] == good["rider_message"]
    assert bundle.gate.count(tracing.GUIDE_AFTER) == 2
    reasons = [e.reason for e in bundle.gate.events if e.kind == tracing.GUIDE_AFTER]
    assert all("approved sentences, verbatim" in r for r in reasons)
    # the injected sentence never entered the conversation as an accepted plan
    accepted = [
        b["toolUse"]["input"]["rider_message"]
        for m in bundle.agent.messages
        for b in m["content"]
        if "toolUse" in b and b["toolUse"]["name"] == "Plan"
    ]
    assert accepted == [good["rider_message"]]


def test_delivery_falls_back_to_code_when_the_model_never_complies(fixture_stack):
    """Strands 1.55.1 re-calls the model without limit while a steering Guide
    keeps rejecting the response (the retry loop runs inside one turn, so a
    turn limit never fires). build_agent therefore caps model calls per run;
    at the cap, code composes the plan and the rider still gets one."""
    kb, policy = fixture_stack
    d = policy(TRIP)
    bad = {**composed_plan(d), "option": "transit", "added_minutes": 99, "rider_message": INJECTION}
    model = ScriptedModel(
        [tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1")]
        + [plan_call(bad, f"p{i}") for i in range(60)]
    )
    bundle = build_agent(model, kb, policy, TRIP, max_model_calls=10)
    out = deliver(bundle, max_turns=6)
    assert out.composed_by == "code" and out.stop_reason == "exception" and "hard cap of 10 model calls" in out.reason
    assert out.plan == composed_plan(d)
    assert model.calls == 10  # the per-run cap bounded the model; the turn limit alone would not have
    assert is_approved(out.plan["rider_message"], d)


def test_delivery_reports_a_pause_instead_of_composing(fixture_stack, tmp_path):
    from le_dispatch.interrupts import DecisionInterruptHandler, DecisionMemory, Inbox

    kb, policy = fixture_stack
    dark = Trip("r1", "DELN", "EMBR", ("DELN-E1",), after_dark=True)
    d = policy(dark)
    handler = DecisionInterruptHandler(
        policy=policy, trip=dark, inbox=Inbox(tmp_path / "inbox.json"), memory=DecisionMemory()
    )
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
            plan_call(composed_plan(d), "p1"),
        ]
    )
    bundle = build_agent(model, kb, policy, dark, extra_plugins=(handler,))
    out = deliver(bundle)
    assert out.composed_by == "none" and out.stop_reason == "interrupt" and out.plan is None


def test_approval_fuzz_accepts_only_whitespace_and_trailing_punctuation_variants(fixture_stack):
    """The false-accept surface of the approved-sentence check is exactly: extra whitespace and trailing
    '.', '!' or spaces. Every other single edit of an approved sentence (a character inserted, deleted or
    swapped, a word appended, a digit changed, a look-alike letter) is rejected. Seeded, deterministic."""
    import random

    kb, policy = fixture_stack
    d = policy(TRIP)
    approved = approved_messages(d)
    assert approved
    rng = random.Random(20260913)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789 ,;:'-"
    accepted_variants = rejected = 0
    for _ in range(600):
        base = rng.choice(approved)
        kind = rng.choice(("insert", "delete", "swap", "append", "digit", "lookalike", "ws", "trail"))
        i = rng.randrange(len(base))
        if kind == "insert":
            m = base[:i] + rng.choice(alphabet) + base[i:]
        elif kind == "delete":
            m = base[:i] + base[i + 1 :]
        elif kind == "swap":
            c = rng.choice(alphabet.replace(base[i], "") or "x")
            m = base[:i] + c + base[i + 1 :]
        elif kind == "append":
            m = base + " Take a taxi instead."
        elif kind == "digit":
            digits = [k for k, ch in enumerate(base) if ch.isdigit()]
            if not digits:
                continue
            k = rng.choice(digits)
            m = base[:k] + str((int(base[k]) + 1) % 10) + base[k + 1 :]
        elif kind == "lookalike":
            if "e" not in base:
                continue
            m = base.replace("e", "е", 1)  # Cyrillic ie
        elif kind == "ws":
            m = "  " + base.replace(" ", "  ", 1) + "\n"
        else:
            m = base.rstrip(".") + rng.choice(("!!", ".", " . ", "!  "))
        harmless = normalize(m) == normalize(base)
        if kind in ("ws", "trail"):
            assert harmless and is_approved(m, d), (kind, m)
            accepted_variants += 1
        elif harmless:
            continue  # an edit that happened to be pure whitespace or trailing punctuation
        else:
            assert not is_approved(m, d), (kind, m)
            rejected += 1
    assert accepted_variants > 50 and rejected > 300


def test_draft_plan_returns_the_approved_sentences_so_a_live_model_sees_them_before_its_first_plan():
    """The tool result carries approved_messages; a model that copies one passes the gate on its first Plan
    (the plan-gate rejection still lists them for a model that did not read the tool result)."""
    import json

    from le_dispatch.interfaces import fixture_policy
    from le_dispatch.plan import make_tools

    kb, policy = fixture_policy()
    d = policy(TRIP)
    (draft_plan,) = make_tools(kb, policy, TRIP)
    result = json.loads(draft_plan(station=d.station, elevator=d.elevator, option=d.top_option))
    assert result["approved_messages"] == approved_messages(d) and len(result["approved_messages"]) == 4
    assert result["policy_top_option"] == d.top_option and result["added_minutes"] == d.minutes_for(d.top_option)
    assert all(is_approved(m, d) for m in result["approved_messages"])


def test_every_sentence_and_card_over_every_case_reads_aloud_cleanly(fixture_stack):
    """Over all 194 cases and both flags: no label with an underscore, no 'None', no double space, no
    unfinished clause in anything the rider hears; every approved sentence is accepted by the check."""
    from le_dispatch.interfaces import load_cases
    from le_dispatch.interrupts import card_question

    kb, policy = fixture_stack
    seen_options = set()
    other = "EMBR"
    for i, case in enumerate(load_cases()):
        far = other if case.station != other else "MONT"
        trips = [  # the outage at the start, at the destination, at a transfer
            Trip(f"r{i}", case.station, far, (case.elevator,)),
            Trip(f"r{i}", far, case.station, (case.elevator,)),
            Trip(f"r{i}", far, "MONT" if far != "MONT" else "16TH", (case.elevator,), via=(case.station,)),
        ]
        for base in trips:
            for flags in ({}, {"after_dark": True}, {"last_train": True}, {"after_dark": True, "last_train": True}):
                trip = replace(base, **flags)
                d = policy(trip)
                seen_options.add(d.top_option)
                texts = approved_messages(d) + hold_messages(d) + [card_question(d)]
                for text in texts:
                    assert "_" not in text and "None" not in text and "  " not in text, text
                    assert text.endswith((".", "?")) and (text[0].isupper() or text[0].isdigit()), text
                    assert d.elevator in text and d.spoken_station in text, text
                where = {"cannot_enter": "starting station", "cannot_exit": "destination", "transfer": "transfer"}
                assert where[d.kind] in approved_messages(d)[0], (d.kind, approved_messages(d)[0])
                assert len(approved_messages(d)[0]) <= 160, approved_messages(d)[0]  # the notification budget
                assert all(is_approved(m, d) for m in approved_messages(d))
                assert all(is_approved(m, d, "hold") for m in hold_messages(d))
    assert seen_options >= {"alternate_elevator", "backtracking"}  # the fixture never ranks transit first
    from le_dispatch.portability import synthetic_agency

    kb2, cases2, policy2 = synthetic_agency()  # names, and transit on top for some elevators
    tops = set()
    for c in cases2:
        d = policy2(Trip("r", c.station, "BTN1" if c.station != "BTN1" else "ATN0", (c.elevator,), after_dark=True))
        tops.add(d.top_option)
        for text in approved_messages(d) + hold_messages(d) + [card_question(d)]:
            assert "_" not in text and "None" not in text and "  " not in text and " Town" in text, text
    assert tops == {"backtracking", "alternate_elevator"}  # two options per elevator: transit is never first
    from le_dispatch.interfaces import PolicyDecision, RankedOption

    transit = PolicyDecision(
        affected=True,
        kind="cannot_enter",
        station="WARM",
        elevator="WARM-E1",
        top_option="transit",
        ranked=[RankedOption("transit", True, "Take AC Transit line 99 from the plaza.", 25, "https://x.invalid")],
        flags={"last_train": True},
        station_name="Warm Springs",
    )
    for text in approved_messages(transit) + hold_messages(transit) + [card_question(transit)]:
        assert "_" not in text and "Warm Springs" in text and "transit connection" in text, text
    assert "This is the last train." in card_question(transit)
