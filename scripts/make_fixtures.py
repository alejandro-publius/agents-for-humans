"""Regenerate fixtures/kb.json and fixtures/cases.json deterministically.

These are FIXTURES that match the documented interface shapes in
le_dispatch/interfaces.py. They are not the frozen KB. The station codes are
BART's public station abbreviations; the elevator ids, option texts and
minutes are synthetic. The laptop session replaces both files with exports
from the real `kb/` package at tag kb-labels-v1 (see docs/INTEGRATION.md).
Label counts mirror the real KB (55 alternate_elevator, 53 backtracking,
86 transit; 194 options across 97 elevators at 50 stations).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures"

STATIONS = [
    "12TH",
    "16TH",
    "19TH",
    "24TH",
    "ANTC",
    "ASHB",
    "BALB",
    "BAYF",
    "BERY",
    "CAST",
    "CIVC",
    "COLM",
    "COLS",
    "CONC",
    "DALY",
    "DBRK",
    "DELN",
    "DUBL",
    "EMBR",
    "FRMT",
    "FTVL",
    "GLEN",
    "HAYW",
    "LAFY",
    "LAKE",
    "MCAR",
    "MLBR",
    "MLPT",
    "MONT",
    "NBRK",
    "NCON",
    "OAKL",
    "ORIN",
    "PCTR",
    "PHIL",
    "PITT",
    "PLZA",
    "POWL",
    "RICH",
    "ROCK",
    "SANL",
    "SBRN",
    "SFIA",
    "SHAY",
    "SSAN",
    "UCTY",
    "WARM",
    "WCRK",
    "WDUB",
    "WOAK",
]
assert len(STATIONS) == 50 and len(set(STATIONS)) == 50

LABELS = ["alternate_elevator", "backtracking", "transit", "mitigation_trip", "mitigation_shuttle"]
LABEL_COUNTS = {"alternate_elevator": 55, "backtracking": 53, "transit": 86}
MINUTES = {"alternate_elevator": 4, "backtracking": 12, "transit": 20}
TEXT = {
    "alternate_elevator": "Use the {alt} elevator on the other side of the platform; ramp connects at concourse level.",
    "alternate_elevator_single": (
        "Use the accessible ramp from the far entrance to the platform; no second elevator is needed."
    ),
    "backtracking": "Ride one stop past to {next} and return on the opposite platform, where the elevator works.",
    "transit": "Take AC Transit or Muni from {code} to the next accessible station; BART honors the fare.",
}


def build() -> tuple[dict, dict]:
    # 97 elevators: two per station except the first three stations, which get one.
    elevators: list[str] = []
    for i, code in enumerate(STATIONS):
        n = 1 if i < 3 else 2
        for k in range(1, n + 1):
            elevators.append(f"{code}-E{k}")
    assert len(elevators) == 97, len(elevators)

    # 194 labels in BART order blocks, then dealt across elevators two at a time,
    # so every elevator has exactly two options and the totals match the KB.
    labels = (["alternate_elevator"] * 55) + (["backtracking"] * 53) + (["transit"] * 86)
    assert len(labels) == 194
    cases = []
    li = 0
    for _slot in range(2):
        for ev in elevators:
            label = labels[li]
            li += 1
            code = ev.split("-")[0]
            idx = STATIONS.index(code)
            alt = f"{code}-E{3 - int(ev[-1])}"
            key = label
            if label == "alternate_elevator" and alt not in elevators:
                key = "alternate_elevator_single"  # single-elevator stations name no second elevator
            text = TEXT[key].format(alt=alt, next=STATIONS[(idx + 1) % 50], code=code)
            cases.append(
                {
                    "case_id": f"C{len(cases) + 1:03d}",
                    "station": code,
                    "elevator": ev,
                    "label": label,
                    "option_text": text,
                    "added_minutes": MINUTES[label],
                    "source_url": f"https://www.bart.gov/stations/{code.lower()}/accessible",
                }
            )
    assert len(cases) == 194
    counts = {lab: sum(1 for c in cases if c["label"] == lab) for lab in LABEL_COUNTS}
    assert counts == LABEL_COUNTS, counts

    kb = {
        "source": "FIXTURE: BART public station abbreviations; elevator ids synthetic. Replace with kb export.",
        "frozen_tag": "fixture (not kb-labels-v1)",
        "stations": STATIONS,
        "elevators": elevators,
        "option_labels": LABELS,
    }
    cases_doc = {
        "source": "FIXTURE: synthetic option rows shaped like the 194 frozen cases. Replace with kb export.",
        "frozen_tag": "fixture (not kb-labels-v1)",
        "label_counts": counts,
        "cases": cases,
    }
    return kb, cases_doc


def main() -> None:
    OUT.mkdir(exist_ok=True)
    kb, cases_doc = build()
    (OUT / "kb.json").write_text(json.dumps(kb, indent=2) + "\n")
    (OUT / "cases.json").write_text(json.dumps(cases_doc, indent=2) + "\n")
    print(f"wrote {OUT / 'kb.json'} ({len(kb['stations'])} stations, {len(kb['elevators'])} elevators)")
    print(f"wrote {OUT / 'cases.json'} ({len(cases_doc['cases'])} cases, {cases_doc['label_counts']})")


if __name__ == "__main__":
    main()
