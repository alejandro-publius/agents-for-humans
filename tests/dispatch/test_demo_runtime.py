"""The runtime demo walks every state of the entrypoint offline, in a fixed order, and prints it."""

from __future__ import annotations

import importlib.util

from le_dispatch.interfaces import ROOT


def test_the_runtime_demo_walks_every_state(capsys):
    spec = importlib.util.spec_from_file_location("demo_runtime_script", ROOT / "scripts" / "demo_runtime.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main([]) == 0
    out = capsys.readouterr().out
    states = [line.split("-> ")[1].split(" ")[0] for line in out.splitlines() if "-> " in line]
    assert states == [
        "sent",
        "already_sent",
        "sent",
        "quiet",
        "pending",
        "pending",
        "sent",
        "already_sent",
        "pending",
        "held",
        "quiet",
        "pending",
        "pending",
        "sent",
        "sent",
        "sent",
        "sent",
        "invalid",
    ]
    assert "nothing is called" in out and "every call well formed" in out
    assert out.count("(model:") == 8  # every delivered plan was the model's
    assert "(note read by model: avoid_ramps)" in out and "(model: transit," in out  # the rider's words applied
    assert "(note read by model: nothing ruled out)" in out  # the note that gave orders changed nothing
    assert out.count("(question closed: 1)") == 1  # the morning poll closed the night's question
    assert out.count("Memory degraded:") == 1 and "1 write kept" in out  # delivered while Memory was down
    assert out.count("Memory back: 1 write replayed") == 1  # and the durable copy caught up
    assert out.count("(decision forgotten: 1)") == 1  # the no went with its outage; the next one asked afresh
    assert out.count("(conversation closed)") == 2  # and so did the conversation, both times the elevator came back


def test_the_brief_demo_tells_the_run_in_plain_lines(capsys):
    """make demo-one-brief: what code decided, what the model tried (three times), what stopped it each time,
    what reached the rider, in words with no JSON; every line from the decision, the events and the plan."""
    spec = importlib.util.spec_from_file_location("demo_one_script", ROOT / "scripts" / "dispatch" / "demo_one.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--brief"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("code decided: DELN elevator DELN-E1 is out at your starting station")
    assert out.count("the model tried (") == 3 and out.count("what stopped it:") == 3
    assert "the hook cancelled it before the tool ran" in out
    assert "the steering gate before the tool sent it back with BART's order" in out
    assert "the steering gate after the model threw the plan away" in out
    assert "what reached the rider: alternate_elevator at DELN (DELN-E1), 4 minutes more" in out
    assert out.rstrip().endswith("models propose, code decides") and "{" not in out
