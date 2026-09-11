"""A4. The evals runner writes counts, refuses unlabeled cases, and never touches the network."""

import json

import pytest

from evals import run as evals_run


def test_missing_label_exits_non_zero(tmp_path, monkeypatch):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "bad.json").write_text(
        json.dumps({"suite": "bad", "output_of": "plan_option", "cases": [{"name": "no_label", "input": {}}]})
    )
    monkeypatch.setattr(evals_run, "CASES_DIR", cases_dir)

    with pytest.raises(evals_run.MissingLabel, match="no_label"):
        evals_run.load_suites()
    assert evals_run.main(["--out", str(tmp_path / "out")]) == 2


def test_full_run_writes_summary_with_counts(tmp_path):
    assert evals_run.main(["--out", str(tmp_path)]) == 0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["provider"] == "mock"
    assert summary["cases_run"] > 0
    assert summary["cases_run"] == sum(s["cases_run"] for s in summary["suites"].values())
    assert summary["network_attempts"] == 0
    for suite in summary["suites"]:
        assert (tmp_path / f"{suite}.json").exists()
