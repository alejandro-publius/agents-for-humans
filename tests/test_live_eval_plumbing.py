"""The live-eval path is exercised offline: call counting, the hard cap, suite filter, the freeze."""

import json

import pytest
from strands import Agent

from agent.counting_model import BudgetExhausted, CallBudget, CountingModel
from agent.mock_model import MockModel
from evals import run as evals_run


def test_counting_model_counts_and_enforces_a_hard_cap(no_network):
    budget = CallBudget(cap=2)
    turns = [{"type": "text", "text": t} for t in ("one", "two", "x")]
    inner = MockModel(turns)
    model = CountingModel(inner, budget)
    agent = Agent(model=model, tools=[], callback_handler=None)
    agent("a")
    agent("b")
    assert budget.used == 2 and budget.exhausted and len(model.calls) == 2
    with pytest.raises(BudgetExhausted):
        agent("c")
    assert inner.turns_remaining == 1, "the capped call never reached the inner model"
    assert no_network.attempts == []


def test_suite_filter_runs_only_the_named_suite(tmp_path):
    assert evals_run.main(["--suite", "harness_hook", "--out", str(tmp_path)]) == 0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert list(summary["suites"]) == ["harness_hook"]
    assert evals_run.main(["--suite", "nope", "--out", str(tmp_path)]) == 2


def test_mock_run_never_overwrites_a_frozen_live_result(tmp_path):
    entry = {"mode": "bedrock", "frozen": True, "agreement_pct": 12.3, "cases_run": 40}
    frozen = {"suite": "policy_agreement", "frozen": True, "enforced": entry}
    (tmp_path / "policy_agreement.json").write_text(json.dumps(frozen))
    assert evals_run.main(["--suite", "policy_agreement", "--out", str(tmp_path)]) == 0
    assert evals_run.main(["--no-steering", "--out", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "policy_agreement.json").read_text()) == frozen
    mock = json.loads((tmp_path / "policy_agreement.mock.json").read_text())
    assert mock["enforced"]["mode"] == "mock" and mock["enforced"]["cases_run"] == 194
    assert mock["no_steering"]["steering"] is False
    assert "get_station_facts" not in mock["no_steering"]["tools"]
    assert mock["no_steering"]["cases_run"] == 194


def test_live_run_refuses_without_credentials_and_refuses_to_reclobber(tmp_path, monkeypatch):
    for var in evals_run.LIVE_ENV_NAMES:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit, match="credentials are not set"):
        evals_run.main(["--provider", "bedrock", "--suite", "policy_agreement", "--out", str(tmp_path)])
    frozen = {"suite": "policy_agreement", "frozen": True, "enforced": {"mode": "bedrock", "frozen": True}}
    (tmp_path / "policy_agreement.json").write_text(json.dumps(frozen))
    live = ["--provider", "bedrock", "--suite", "policy_agreement", "--out", str(tmp_path)]
    assert evals_run.main(live) == 4
    with pytest.raises(SystemExit, match="credentials are not set"):  # the other entry is not frozen
        evals_run.main([*live, "--no-steering"])
    assert evals_run.main(["--provider", "bedrock", "--ablate", "--out", str(tmp_path)]) == 2


def test_model_specific_entry_names_keep_sonnet_and_nova_apart(tmp_path, monkeypatch):
    from evals.run import entry_name, frozen_live_result, model_slug

    assert model_slug(None) == "" and model_slug("us.amazon.nova-lite-v1:0") == "us-amazon-nova-lite-v1-0"
    assert entry_name("enforced", None) == "enforced"
    assert entry_name("no_steering", "us.amazon.nova-lite-v1:0") == "no_steering-us-amazon-nova-lite-v1-0"
    frozen = {"suite": "policy_agreement", "frozen": True, "enforced": {"mode": "bedrock", "frozen": True}}
    (tmp_path / "policy_agreement.json").write_text(json.dumps(frozen))
    assert frozen_live_result(tmp_path, "enforced") is not None
    assert (
        frozen_live_result(tmp_path, "enforced-us-amazon-nova-lite-v1-0") is None
    )  # a Nova run is not blocked
