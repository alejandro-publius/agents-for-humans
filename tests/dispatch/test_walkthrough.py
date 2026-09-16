"""The walkthrough page cannot say something the runs did not: every sentence, reason, option, minute and
count on it is checked against the packet or results file it came from."""

from __future__ import annotations

import html
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _module():
    spec = importlib.util.spec_from_file_location("walkthrough", ROOT / "scripts" / "walkthrough.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_every_sentence_on_the_page_comes_from_a_packet_or_a_results_file(tmp_path):
    m = _module()
    assert m.main([str(tmp_path)]) == 0
    page = (tmp_path / "index.html").read_text()
    fragment = (tmp_path / "artifact.html").read_text()
    assert page.startswith("<!doctype html>") and "</html>" in page
    assert not fragment.lstrip().startswith("<!doctype")  # the host supplies the shell
    assert "<title>One Outage at Del Norte</title>" in page and "<title>" in fragment

    packets = {
        name: json.loads((ROOT / "docs" / "evidence" / f"{name}.json").read_text())
        for name in ("DELN-E1-daytime", "DELN-E1-note", "DELN-E1-after-dark-yes", "DELN-E1-after-dark-no")
    }
    # the four rider messages, verbatim (the yes and no ones travel as JSON into the script)
    for name in ("DELN-E1-daytime", "DELN-E1-note"):
        assert html.escape(packets[name]["final_plan"]["rider_message"]) in page, name
    for name in ("DELN-E1-after-dark-yes", "DELN-E1-after-dark-no"):
        assert json.dumps(packets[name]["final_plan"]["rider_message"])[1:-1] in page, name
    card = packets["DELN-E1-after-dark-yes"]["decision_card"]
    assert html.escape(card["question"]) in page
    assert card["source_url"] in page and str(card["added_minutes"]) in page
    assert html.escape(card["rejected"][0]["reason"]) in page
    assert html.escape(packets["DELN-E1-note"]["note"]["text"]) in page
    # every gate reason the ledger shows is the packet's own
    for event in packets["DELN-E1-daytime"]["gate_events"]:
        if event["kind"].startswith(("hook.", "steering.guide")):
            assert html.escape(event["reason"], quote=True) in page, event["kind"]

    results = {
        n: json.loads((ROOT / "results" / n).read_text())
        for n in ("quiet.json", "runtime_sweep.json", "red_team_exhaustive.json", "gate_ablation.json")
    }
    q = results["quiet.json"]
    for key in ("days", "trips_checked", "quiet_trips", "plans_sent_in_background", "interruptions"):
        assert f'<p class="fig">{q[key]}</p>' in page, key
    assert q["opening_line"] in page
    assert f"<strong>{results['runtime_sweep.json']['cases']}</strong>" in page
    assert str(results["runtime_sweep.json"]["invocations"]) in page
    assert str(results["red_team_exhaustive.json"]["runs"]) in page
    leaked = results["gate_ablation.json"]["configs"]["without_after_model_gate"]["leaked_runs"]
    runs = results["gate_ablation.json"]["configs"]["all_gates"]["runs"]
    assert f"{leaked} of {runs}" in page
    assert "fixture run" in page.lower()  # the label stays until the laptop reruns


def test_the_page_is_keyboard_and_screen_reader_shaped(tmp_path):
    m = _module()
    m.main([str(tmp_path)])
    page = (tmp_path / "index.html").read_text()
    assert 'aria-live="polite"' in page  # the answer's outcome is announced
    assert page.count('aria-pressed="false"') == 2 and 'role="group"' in page
    assert 'aria-label="Answer the decision card"' in page and 'aria-label="The four scenes"' in page
    assert "prefers-reduced-motion" in page and "prefers-color-scheme" in page
    assert ':root[data-theme="dark"]' in page and "--paper" in page
    assert '<button type="button"' in page and "onclick=" not in page
    assert "<main>" in page and page.count('aria-labelledby="h-') == 5  # named regions, axe clean
