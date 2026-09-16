"""Score the agent's interruptions against two independent human labels -> results/relevance.json.

    python -m evals.relevance          # reads evals/labels/relevance.csv

Truth for a row is the label when both labelers agree; rows where they disagree are counted, not
scored. Precision and recall are for ``agent_sent`` against truth == relevant. Inter-labeler
agreement is percent agreement and Cohen's kappa over rows both labelers filled in. With no labels,
the file says so and every metric is null. Numbers are never invented.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "evals" / "labels" / "relevance.csv"
OUT = REPO_ROOT / "results" / "relevance.json"
VALID = {"relevant", "not"}


def score(rows: list[dict[str, str]]) -> dict[str, Any]:
    labeled = [r for r in rows if r.get("label_1") in VALID and r.get("label_2") in VALID]
    agree = [r for r in labeled if r["label_1"] == r["label_2"]]
    disagree = len(labeled) - len(agree)

    kappa = percent = None
    if labeled:
        percent = round(100.0 * len(agree) / len(labeled), 1)
        n = len(labeled)
        p1 = sum(r["label_1"] == "relevant" for r in labeled) / n
        p2 = sum(r["label_2"] == "relevant" for r in labeled) / n
        expected = p1 * p2 + (1 - p1) * (1 - p2)
        observed = len(agree) / n
        kappa = None if expected == 1 else round((observed - expected) / (1 - expected), 3)

    precision = recall = None
    tp = fp = fn = tn = 0
    for r in agree:
        truth = r["label_1"] == "relevant"
        sent = r.get("agent_sent") == "1"
        tp += truth and sent
        fp += (not truth) and sent
        fn += truth and (not sent)
        tn += (not truth) and (not sent)
    if tp + fp:
        precision = round(100.0 * tp / (tp + fp), 1)
    if tp + fn:
        recall = round(100.0 * tp / (tp + fn), 1)

    status = "scored" if agree else ("labels disagree on every row" if labeled else "awaiting labels")
    return {
        "status": status,
        "rows_total": len(rows),
        "rows_labeled_by_both": len(labeled),
        "rows_labelers_agree": len(agree),
        "rows_labelers_disagree": disagree,
        "agent_sent_total": sum(r.get("agent_sent") == "1" for r in rows),
        "precision_pct": precision,
        "recall_pct": recall,
        "inter_labeler_percent_agreement": percent,
        "inter_labeler_cohen_kappa": kappa,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "note": (
            "Truth = the label when both labelers agree. Precision/recall are for agent_sent against "
            "truth == relevant. Null means not computable from the labels present; nothing is estimated."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    csv_path = Path(argv[0]) if argv else CSV_PATH
    rows = list(csv.DictReader(csv_path.open(newline=""))) if csv_path.exists() else []
    shown = csv_path.relative_to(REPO_ROOT) if csv_path.is_relative_to(REPO_ROOT) else csv_path
    result = {"labels_csv": str(shown), **score(rows)}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"relevance: {result['status']}; rows={result['rows_total']} "
        f"labeled_by_both={result['rows_labeled_by_both']} "
        f"precision={result['precision_pct']} recall={result['recall_pct']} "
        f"agreement={result['inter_labeler_percent_agreement']} "
        f"kappa={result['inter_labeler_cohen_kappa']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
