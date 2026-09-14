"""F7: the two-model live eval runner offline, the hard cap, the table generator."""

from __future__ import annotations

import json

import pytest
from le_dispatch.eval_live import (
    BudgetedModel,
    BudgetExceeded,
    LiveModel,
    credentials_present,
    load_entries,
    load_models,
    merge_entries,
    planned_entries,
    render_readme_section,
    render_table,
    run_all,
)
from le_dispatch.interfaces import FIXTURES, load_cases
from le_dispatch.messages import approved_messages
from le_dispatch.scripted_model import ScriptedModel, plan_call, text_turn, tool_call


def test_models_config_has_two_models_and_two_modes():
    cfg = load_models()
    assert [m.name for m in cfg["models"]] == ["sonnet", "nova-lite"]
    assert cfg["modes"] == ["enforced", "no_steering"] and cfg["hard_cap_calls_per_entry"] == 200
    assert cfg["models"][0].model_id.startswith("us.anthropic.claude-sonnet")
    assert cfg["models"][1].model_id.startswith("us.amazon.nova-lite")
    assert len(planned_entries(cfg)) == 4
    assert credentials_present() is False


def test_budget_cap_is_enforced():
    inner = ScriptedModel([text_turn("x")] * 5)
    model = BudgetedModel(inner, cap=3, label="t")

    async def drain():
        for _ in range(3):
            async for _ev in model.stream([]):
                pass
        with pytest.raises(BudgetExceeded):
            async for _ev in model.stream([]):
                pass

    import asyncio

    asyncio.run(drain())
    assert model.calls == 3


class PerRunScripted(ScriptedModel):
    """One script per agent run: a new run starts when the conversation holds
    only the user prompt, so a wrong first attempt in enforced mode retries
    within the same case instead of desynchronizing the next case."""

    def __init__(self, scripts, name="scripted"):
        super().__init__([], name=name)
        self.scripts = scripts
        self.run = -1

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        if len(messages) == 1:
            self.run += 1
            self.steps = list(self.scripts[self.run])
            self.calls = 0
        async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
            yield event


def scripted_factory(policy, cases, agree_every=True):
    """A model factory that answers each case correctly, or every other case wrongly twice then correctly."""

    def make(model: LiveModel):
        from le_dispatch.eval_live import case_trip

        scripts = []
        for i, case in enumerate(cases):
            d = policy(case_trip(case, i))
            good_args = {"station": d.station, "elevator": d.elevator, "option": d.top_option}
            good_plan = {
                **good_args,
                "added_minutes": d.minutes_for(d.top_option),
                "rider_message": approved_messages(d)[0],
            }
            steps = []
            if not agree_every and i % 2 == 1:
                wrong = "transit" if d.top_option != "transit" else "backtracking"
                bad_plan = {**good_plan, "option": wrong, "added_minutes": d.minutes_for(wrong)}
                steps.append(tool_call("draft_plan", {**good_args, "option": wrong}, f"t{i}w"))
                steps.append(plan_call(bad_plan, f"p{i}w"))
            steps += [tool_call("draft_plan", good_args, f"t{i}"), plan_call(good_plan, f"p{i}")]
            scripts.append(steps)
        return PerRunScripted(scripts, name=model.model_id)

    return make


def test_runner_writes_four_entries_with_model_ids(fixture_stack, tmp_path):
    kb, policy = fixture_stack
    cases = load_cases()[:6]
    cfg = load_models()
    entries = run_all(cfg, cases, kb, policy, model_factory=scripted_factory(policy, cases, agree_every=True))
    assert len(entries) == 4
    assert {e["model_id"] for e in entries} == {m.model_id for m in cfg["models"]}
    assert all(e["cases"] == 6 and e["hard_cap_calls"] == 200 for e in entries)
    # the models are "bedrock" in the config but the data is the fixture: not claimable, and the table says why
    assert all(e["claimable"] is False and e["source"]["fixture"] is True for e in entries)
    assert "live model on the fixture cases" in render_table(entries)
    assert all(e["agreement_pct"] == 100.0 for e in entries)
    doc = merge_entries(entries, tmp_path / "policy_agreement.json")
    assert len(doc["entries"]) == 4
    doc = merge_entries(entries, tmp_path / "policy_agreement.json")  # rerun replaces, never duplicates
    assert len(doc["entries"]) == 4


def test_no_steering_leaks_and_enforced_corrects(fixture_stack):
    """Plumbing proof only: a model wrong on every other case scores 50 percent
    without steering and 100 percent with it, because the gates make it retry.
    Never cite this as an ablation result; the live rows are the result."""
    kb, policy = fixture_stack
    cases = load_cases()[:4]
    cfg = load_models()
    entries = run_all(cfg, cases, kb, policy, model_factory=scripted_factory(policy, cases, agree_every=False))
    by_mode = {(e["model_name"], e["mode"]): e for e in entries}
    assert by_mode[("sonnet", "no_steering")]["agree"] == 2 and by_mode[("sonnet", "no_steering")]["cases"] == 4
    assert by_mode[("sonnet", "enforced")]["agree"] == 4
    assert by_mode[("sonnet", "enforced")]["calls_used"] > by_mode[("sonnet", "no_steering")]["calls_used"]


def test_table_renders_fixture_with_four_live_rows():
    entries = load_entries(FIXTURES / "policy_agreement_live.json")
    live = [e for e in entries if e["provider"] == "bedrock"]
    assert len(live) == 4
    table = render_table(entries)
    rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| Provider")]
    assert len(rows) == 7
    assert "88.1%" in table and "77.3%" in table and "`us.amazon.nova-lite-v1:0`" in table
    assert "plumbing proof only, never an ablation result" in table
    assert table.count("| live |") == 5
    section = render_readme_section(entries)
    assert section.startswith("Policy agreement:") and "7 (5 live)" in section
    # missing numbers render as TODO, never as a made-up value
    assert "TODO" in render_table([{"provider": "bedrock", "model_id": "x", "mode": "enforced"}])


def test_results_file_in_repo_renders(tmp_path):
    entries = load_entries()
    table = render_table(entries)
    assert json.dumps(entries)  # serializable
    assert "| Provider |" in table
    if any(e.get("provider") == "mock" and e.get("mode") == "no_steering" for e in entries):
        assert "never an ablation result" in table  # the mock ablation row is always labelled


def test_budgeted_model_exposes_the_wrapped_models_config_for_the_trace():
    """Strands reads model.config["model_id"] into the invoke_agent span when the attribute exists; the
    wrapper must not hide it, or a live run's evidence packet would carry no model id."""

    class WithConfig(ScriptedModel):
        config = {"model_id": "us.amazon.nova-lite-v1:0", "temperature": 0}

    assert BudgetedModel(WithConfig([text_turn("x")]), cap=1).config["model_id"] == "us.amazon.nova-lite-v1:0"
    plain = BudgetedModel(ScriptedModel([text_turn("x")]), cap=1)  # no config attribute: falls back to get_config()
    assert plain.config == plain.get_config()


def test_a_never_complying_case_is_a_disagreement_and_only_the_entry_cap_stops_the_entry(fixture_stack):
    """The per-run cap (24 calls) inside one case must not end the whole entry: the case counts as
    composed by code and the next case runs. The entry-wide cap is the only early stop."""
    from le_dispatch.eval_live import LiveModel, case_trip, run_entry

    kb, policy = fixture_stack
    cases = load_cases()[:3]

    def factory(model: LiveModel):
        scripts = []
        for i, case in enumerate(cases):
            d = policy(case_trip(case, i))
            good_args = {"station": d.station, "elevator": d.elevator, "option": d.top_option}
            good_plan = {
                **good_args,
                "added_minutes": d.minutes_for(d.top_option),
                "rider_message": approved_messages(d)[0],
            }
            if i == 1:  # never complies: 40 wrong plans, more than the per-run cap
                scripts.append(
                    [tool_call("draft_plan", good_args, "t")]
                    + [plan_call({**good_plan, "added_minutes": 1}, f"p{k}") for k in range(40)]
                )
            else:
                scripts.append([tool_call("draft_plan", good_args, f"t{i}"), plan_call(good_plan, f"p{i}")])
        return PerRunScripted(scripts, name=model.model_id)

    live = LiveModel(name="s", provider="scripted", model_id="scripted-x")
    entry = run_entry(live, "enforced", cases, kb, policy, model_factory=factory, cap=200)
    assert entry["cases"] == 3 and entry["agree"] == 2 and entry["composed_by_code"] == 1
    assert entry["stopped_early"] is None and 24 <= entry["calls_used"] <= 30

    small = run_entry(live, "enforced", cases, kb, policy, model_factory=factory, cap=10)
    assert small["stopped_early"] and "hard cap of 10" in small["stopped_early"]
    assert small["cases"] == 1 and small["agree"] == 1  # the first case ran; the second tripped the entry cap


def test_eval_live_script_explains_the_cap_and_accepts_overrides(capsys, monkeypatch):
    """The dry run states the arithmetic (200 calls, about 100 cases at two calls each) and --cap and
    --limit-cases change the plan; nothing is called (the conftest strips every credential)."""
    import importlib.util
    import sys

    from le_dispatch.interfaces import ROOT

    spec = importlib.util.spec_from_file_location("eval_live_script", ROOT / "scripts" / "eval_live.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["eval_live_script"] = module
    spec.loader.exec_module(module)
    assert module.main([]) == 0
    out = capsys.readouterr().out
    assert "cap 200 calls" in out and "covers about 100 cases" in out and "nothing called" in out
    assert module.main(["--cap", "1200", "--limit-cases", "40"]) == 0
    out = capsys.readouterr().out
    assert "cap 1200 calls" in out and "cases per entry: 40" in out and "covers about 600 cases" in out


def test_a_provider_that_fails_on_every_call_stops_the_entry_instead_of_filling_it_with_silent_disagreements(
    fixture_stack,
):
    from le_dispatch.eval_live import LiveModel, run_entry

    kb, policy = fixture_stack
    cases = load_cases()[:8]

    class Broken(ScriptedModel):
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            raise RuntimeError("AccessDeniedException: not authorized to invoke this model")
            yield  # pragma: no cover

    live = LiveModel(name="s", provider="scripted", model_id="scripted-broken")
    entry = run_entry(live, "enforced", cases, kb, policy, model_factory=lambda m: Broken([]), cap=200)
    assert entry["stopped_early"] and "three provider errors in a row" in entry["stopped_early"]
    assert "AccessDeniedException" in entry["stopped_early"]
    assert entry["cases"] == 3 and entry["composed_by_code"] == 3 and entry["agree"] == 0


def test_live_rows_become_claimable_on_the_real_exports(fixture_stack, tmp_path, monkeypatch):
    import shutil

    from le_dispatch import interfaces
    from le_dispatch.interfaces import FIXTURES

    kb_export, cases_export = tmp_path / "kb-labels-v1.json", tmp_path / "cases-v1.json"
    shutil.copy(FIXTURES / "kb.json", kb_export)
    shutil.copy(FIXTURES / "cases.json", cases_export)
    monkeypatch.setenv(interfaces.KB_EXPORT_ENV, str(kb_export))
    monkeypatch.setenv(interfaces.CASES_EXPORT_ENV, str(cases_export))
    kb, policy = fixture_stack
    cases = load_cases()[:3]
    entries = run_all(load_models(), cases, kb, policy, model_factory=scripted_factory(policy, cases))
    assert all(e["claimable"] is True and e["source"]["fixture"] is False for e in entries)
    assert "live" in render_table(entries) and "fixture cases" not in render_table(entries)


def test_a_stand_in_row_is_labelled_as_plumbing_proof_if_it_is_ever_rendered():
    from le_dispatch.eval_live import _status

    row = {"provider": "stand-in", "model_id": "x", "mode": "enforced", "cases": 5, "agree": 5, "claimable": False}
    assert "plumbing proof only, never a result" in _status(row)
