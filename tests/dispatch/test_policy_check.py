"""The real policy engine against the frozen cases: drift is visible before any result is cited."""

from __future__ import annotations

import dataclasses
import json

import pytest
from le_dispatch.interfaces import Trip, load_cases
from le_dispatch.policy_check import compare, load_policy, render, write_results


def test_the_case_backed_policy_agrees_with_itself_on_every_case(fixture_stack, tmp_path):
    kb, policy = fixture_stack
    doc = compare(load_cases(), kb, policy, policy)
    assert doc["cases"] == 194 and doc["agree"] == 194 and doc["disagree"] == 0 and doc["agreement_pct"] == 100.0
    assert doc["source_url_differs"] == 0 and doc["provenance"]["claimable"] is False
    write_results(doc, tmp_path / "pea.json")
    assert json.loads((tmp_path / "pea.json").read_text())["agree"] == 194
    assert render(doc).startswith("policy engine agreement: 194/194 cases (100.0%)")
    doc["provenance"]["run"] = "the case-backed policy against itself (plumbing proof; pass --policy)"
    assert "(100.0% of the plumbing proof)" in render(doc)  # the self-check says what its 100 percent is


def test_a_drifting_engine_is_listed_case_by_case(fixture_stack):
    """An engine that ranks transit above everything on one station, adds a minute on another, and says
    a third is not affected: three disagreements, each naming the field, the reference and the candidate."""
    kb, policy = fixture_stack
    cases = load_cases()
    drift_stations = {cases[0].station: "option", cases[5].station: "minutes", cases[9].station: "affected"}

    def drifting(trip: Trip):
        d = policy(trip)
        kind = drift_stations.get(trip.origin)
        if kind == "option" and d.affected:
            other = next((o for o in d.ranked if o.label != d.top_option), None)
            if other is not None:
                return dataclasses.replace(d, top_option=other.label)
        if kind == "minutes" and d.affected:
            ranked = [
                dataclasses.replace(o, added_minutes=(o.added_minutes or 0) + 1) if o.label == d.top_option else o
                for o in d.ranked
            ]
            return dataclasses.replace(d, ranked=ranked)
        if kind == "affected":
            return dataclasses.replace(d, affected=False, station=None, elevator=None, top_option=None, ranked=[])
        return d

    doc = compare(cases, kb, policy, drifting)
    assert doc["disagree"] >= 3 and doc["agree"] + doc["disagree"] == 194
    fields = {k for d in doc["disagreements"] for k in d["differs"]}
    assert {"top_option", "minutes", "affected"} <= fields
    text = render(doc)
    assert "disagreement(s)" in text and "vs" in text


def test_load_policy_accepts_a_callable_or_a_factory(tmp_path, monkeypatch):
    """POLICY=package.module:callable, where the callable is the adapter itself or a zero-argument factory."""
    import sys

    (tmp_path / "fake_engine.py").write_text(
        "from le_dispatch.interfaces import fixture_policy\n"
        "_kb, _policy = fixture_policy()\n"
        "def real_policy(trip):\n"
        "    return _policy(trip)\n"
        "def factory():\n"
        "    return real_policy\n"
        "def broken_factory():\n"
        "    return 42\n"
        "NOT_CALLABLE = 1\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("fake_engine", None)
    trip = Trip("r", "DELN", "EMBR", ("DELN-E1",))
    assert load_policy("fake_engine:real_policy")(trip).top_option == "alternate_elevator"
    assert load_policy("fake_engine:factory")(trip).top_option == "alternate_elevator"
    for spec in ("no-colon", "fake_engine:NOT_CALLABLE", "fake_engine:broken_factory"):
        with pytest.raises(ValueError):
            load_policy(spec)
