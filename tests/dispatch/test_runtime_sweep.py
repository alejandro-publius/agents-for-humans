"""F58: the hosted contract over the dataset (le_dispatch/runtime_sweep.py)."""

from __future__ import annotations

import importlib.util
import json

from le_dispatch.interfaces import ROOT, fixture_policy, load_cases
from le_dispatch.runtime_sweep import render, run_sweep, trip_payload


def test_the_sweep_holds_on_a_slice_and_says_what_it_counted(tmp_path):
    """Six cases (two of each kind): every count equals the case count, nothing composed by code, the Memory
    stand-in ok, the three interrupt events on the trace; the rendered summary carries the numbers."""
    kb, policy = fixture_policy()
    cases = load_cases()[:6]
    doc = run_sweep(kb, policy, cases)
    n = len(cases)
    for key in (
        "daytime_sent",
        "agreement",
        "minutes_agreement",
        "one_message",
        "note_orders_ignored",
        "note_only_takes_away",
        "asked_once",
        "superseded",
        "late_answer",
        "held",
        "held_remembered",
        "forgotten",
        "asked_again",
    ):
        assert doc[key] == n, (key, doc[key])
    assert doc["composed_by_code"] == 0 and doc["failures"] == [] and doc["cases"] == n
    assert doc["invocations"] == 12 * n and doc["model_runs"] == 5 * n  # two riders with a note per case
    assert doc["states"] == {"already_sent": 3 * n, "held": n, "pending": 3 * n, "quiet": n, "sent": 4 * n}
    assert doc["kinds"] == {"cannot_enter": 2, "cannot_exit": 2, "transfer": 2}
    assert doc["memory"]["status"] == "ok" and doc["memory"]["events"] > 0
    assert doc["span_events"] == {
        "decision.cleared": n,
        "interrupt.raised": 3 * n,
        "interrupt.resumed": n,
        "interrupt.superseded": n,
    }
    assert doc["provenance"]["claimable"] is False
    text = render(doc)
    assert f"sent {n}/{n}" in text and f"asked once {n}/{n}" in text and "0 composed by code" in text
    assert f"gives orders changed nothing {n}/{n}" in text and f"took one option away and nothing else {n}/{n}" in text
    json.dumps(doc)  # serialisable as written


def test_the_payloads_cover_the_three_kinds_and_never_name_the_outage_station_twice():
    cases = load_cases()[:3]
    seen = set()
    for i, case in enumerate(cases):
        p = trip_payload(case, i, f"r{i}")
        assert p["outages"] == [case.elevator] and p["origin"] != p["destination"]
        seen.add("via" if p.get("via") else ("origin" if p["origin"] == case.station else "destination"))
        assert case.station in {p["origin"], p["destination"], *p.get("via", [])}
    assert seen == {"origin", "destination", "via"}


def test_the_script_writes_the_results_file_and_exits_zero_on_a_complete_slice(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("runtime_sweep_script", ROOT / "scripts" / "runtime_sweep.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = tmp_path / "sweep.json"
    assert script.main(["--cases", "3", "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert doc["cases"] == 3 and doc["agreement"] == 3
    printed = capsys.readouterr().out
    assert "runtime sweep: 3 cases" in printed and "every call well formed" in printed


def test_the_second_agency_runs_through_the_same_entrypoint(tmp_path):
    """The hosted contract is agency-agnostic: the synthetic agency's cases (its own station codes, its own
    published option order, its own sentences) through the same handle(), with its own far stations; every
    counter equals the case count on a slice, and the results say which agency."""
    from le_dispatch.portability import synthetic_agency

    kb, cases, policy = synthetic_agency()
    far = tuple(sorted(kb.stations))[:3]
    doc = run_sweep(kb, policy, cases[:6], far_stations=far, agency="the synthetic second agency")
    n = 6
    for key in ("daytime_sent", "agreement", "minutes_agreement", "note_orders_ignored", "asked_once", "asked_again"):
        assert doc[key] == n, (key, doc[key])
    assert doc["failures"] == [] and doc["composed_by_code"] == 0
    prov = doc["provenance"]
    assert prov["agency"] == "the synthetic second agency" and "synthetic second agency" in prov["run"]
    assert doc["kinds"] == {"cannot_enter": 2, "cannot_exit": 2, "transfer": 2}
    import pytest

    with pytest.raises(ValueError):
        run_sweep(kb, policy, cases[:1], far_stations=("DELN", "EMBR", "MONT"))  # BART's stations are not this agency's
