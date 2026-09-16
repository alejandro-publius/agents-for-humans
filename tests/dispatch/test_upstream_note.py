"""F19: the upstream note reproduces, and the live demo calls nothing without credentials and --yes.

The reproduction in docs/UPSTREAM-NOTE.md is executed as written. If a
future Strands release bounds the after-model retry loop, this test fails
first, which is the signal to retire BudgetedModel's role as the only
bound and to update the note."""

from __future__ import annotations

import importlib.util
import re

from le_dispatch.interfaces import ROOT  # the repo root in either layout (tests/ or tests/dispatch/)

NOTE = ROOT / "docs" / "UPSTREAM-NOTE.md"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_upstream_note_reproduction_runs_as_written(capsys):
    """Strands 1.55.1: fifty model calls under limits={"turns": 2} when the handler keeps guiding."""
    block = re.search(r"```python\n(.*?)```", NOTE.read_text(), re.S)
    assert block, "the note carries a python reproduction"
    namespace: dict = {}
    exec(compile(block.group(1), str(NOTE), "exec"), namespace)  # noqa: S102 (our own documented snippet)
    assert namespace["Talker"].calls == 50  # the turn limit of 2 never fired
    assert namespace["result"].stop_reason == "end_turn"
    assert "stop reason: end_turn model calls: 50" in capsys.readouterr().out  # the line the note quotes


def test_a_handler_that_raises_fails_open_in_strands():
    """The second observation in the note: an exception inside steer_after_model is swallowed and the
    response proceeds; inside steer_before_tool it is swallowed and the tool runs. This is why our
    gates catch their own errors and return Guide."""
    from le_dispatch.scripted_model import ScriptedModel, text_turn, tool_call
    from strands import Agent, tool
    from strands.vended_plugins.steering.core.handler import SteeringHandler

    seen: list[str] = []

    @tool
    def ping(x: str) -> str:
        """Echo."""
        seen.append(x)
        return x

    class Raises(SteeringHandler):
        async def steer_before_tool(self, *, agent, tool_use, **kw):
            raise RuntimeError("boom before")

        async def steer_after_model(self, *, agent, message, stop_reason, **kw):
            raise RuntimeError("boom after")

    model = ScriptedModel([tool_call("ping", {"x": "ran"}, "t1"), text_turn("done")])
    result = Agent(model=model, tools=[ping], plugins=[Raises()], callback_handler=None)("go")
    assert seen == ["ran"] and result.stop_reason == "end_turn"  # nothing stopped either path


def test_the_bedrock_adapter_leaves_botocores_retry_layer_on_by_default():
    """The fifth observation in the note: BedrockModel's default client config sets no retries, so
    botocore's legacy layer retries a throttle underneath the SDK's own strategy. Flips when a Strands
    release configures the client's retries itself; then le_dispatch/live.py can drop its own."""
    from strands.models import BedrockModel

    client = BedrockModel(model_id="us.amazon.nova-lite-v1:0", region_name="us-west-2").client
    assert client.meta.config.retries == {"mode": "legacy"}  # botocore's default, retries a throttle five times


def test_note_names_the_workaround_and_its_test():
    text = NOTE.read_text()
    assert "le_dispatch/budget.py" in text and "deliver()" in text
    named = re.findall(r"`(test_\w+)`", text)
    assert named, "the note names the test that covers the workaround"
    sources = "\n".join(p.read_text() for p in (ROOT / "tests").rglob("test_*.py"))
    for name in named:
        assert re.search(rf"^def {name}\(", sources, re.M), name


def test_demo_live_dry_run_calls_nothing(capsys, monkeypatch):
    """Without credentials the script prints the plan and returns before importing BedrockModel;
    the conftest strips every key and refuses the network, so a call would fail loudly."""
    demo = _load_script("demo_live")
    for argv in ([], ["--yes"], ["--model", "us.amazon.nova-lite-v1:0", "--elevator", "DELN-E1"]):
        assert demo.main(argv) == 0
        out = capsys.readouterr().out
        assert "dry run" in out and "nothing called" in out
        assert "policy engine: " in out and "top option " in out
