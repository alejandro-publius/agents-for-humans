"""C4. Label export keeps human labels; the relevance scorer never invents numbers; poller archives."""

import csv
import json

from app.replay import replay
from app.store import RiderStore
from bart import BartClient
from bart.client import FIXTURES_DIR
from evals.relevance import score
from scripts.export_labels import export
from src.poller import archive_payload, connect


def _replayed(tmp_path):
    store = RiderStore(tmp_path / "riders.sqlite")
    store.seed_demo()
    replay(store, connect(tmp_path / "outages.sqlite"))
    return store


def test_export_one_row_per_decision_and_labels_survive_reexport(tmp_path, no_network):
    _replayed(tmp_path)
    csv_path = tmp_path / "relevance.csv"
    total, added = export(tmp_path / "riders.sqlite", csv_path)
    assert total == added == 8
    rows = list(csv.DictReader(csv_path.open()))
    assert {r["label_1"] for r in rows} == {""} and rows[0]["trip"] in ("SANL->EMBR", "EMBR->PLZA")
    rows[0]["label_1"], rows[0]["label_2"] = "relevant", "relevant"
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    total2, added2 = export(tmp_path / "riders.sqlite", csv_path)
    assert (total2, added2) == (8, 0)
    assert list(csv.DictReader(csv_path.open()))[0]["label_1"] == "relevant"


def test_scorer_reports_awaiting_labels_with_null_metrics():
    rows = [
        {"agent_sent": "1", "label_1": "", "label_2": ""},
        {"agent_sent": "0", "label_1": "", "label_2": ""},
    ]
    r = score(rows)
    assert r["status"] == "awaiting labels"
    assert r["precision_pct"] is None and r["recall_pct"] is None
    assert r["inter_labeler_cohen_kappa"] is None and r["rows_labeled_by_both"] == 0


def test_scorer_precision_recall_and_kappa_on_hand_made_labels():
    rows = [
        {"agent_sent": "1", "label_1": "relevant", "label_2": "relevant"},  # tp
        {"agent_sent": "1", "label_1": "not", "label_2": "not"},  # fp
        {"agent_sent": "0", "label_1": "relevant", "label_2": "relevant"},  # fn
        {"agent_sent": "0", "label_1": "not", "label_2": "not"},  # tn
        {"agent_sent": "1", "label_1": "relevant", "label_2": "not"},  # disagreement, excluded
    ]
    r = score(rows)
    assert r["status"] == "scored"
    assert r["confusion"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert r["precision_pct"] == 50.0 and r["recall_pct"] == 50.0
    assert r["rows_labelers_agree"] == 4 and r["rows_labelers_disagree"] == 1
    assert r["inter_labeler_percent_agreement"] == 80.0
    assert 0.5 < r["inter_labeler_cohen_kappa"] < 0.7


def test_poller_archive_writes_payload_and_manifest(tmp_path):
    payload = BartClient(api_key=None).elevators(fixture=FIXTURES_DIR / "elev_sample.json")
    path = archive_payload(tmp_path / "archive", payload, "2026-09-12T14:00:00+00:00", "fixture:test")
    manifest = json.loads((tmp_path / "archive" / "manifest.json").read_text())
    assert path.exists() and manifest["snapshots"][0]["file"] == path.name
    archive_payload(tmp_path / "archive", payload, "2026-09-12T14:05:00+00:00", "fixture:test")
    assert len(json.loads((tmp_path / "archive" / "manifest.json").read_text())["snapshots"]) == 2
