"""Generate evals/cases/policy_agreement.json: one case per (station, elevator, condition) in the KB.

The label is the KB option label BART's text was classified into (kb/labels.py). Nothing here is
tuned: the case list is a pure function of kb/stations/*.json. Re-run after `python -m kb.build`.

    python -m evals.gen_policy_cases
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kb.load import load_stations  # noqa: E402

OUT = Path(__file__).resolve().parent / "cases" / "policy_agreement.json"
OTHER_END = {"default": "EMBR", "EMBR": "MONT"}  # a destination/origin that is not the outage station


def build_cases() -> list[dict]:
    cases = []
    for abbr, s in sorted(load_stations().items()):
        other = OTHER_END.get(abbr, OTHER_END["default"])
        for e in s["elevators"]:
            for opt in e["outage_options"]:
                if opt["situation"] == "note":
                    continue
                situation = opt["situation"]
                entering = situation.startswith("cant_enter") or situation.startswith("can_t_access")
                trip = {"origin": abbr, "dest": other} if entering else {"origin": other, "dest": abbr}
                label = opt["option_label"]
                name = f"{abbr}__{e['name']}__{opt['situation']}".replace(" ", "_").replace("/", "-")
                cases.append(
                    {
                        "name": name,
                        "input": {
                            "station": abbr,
                            "elevator": e["name"],
                            "situation": opt["situation"],
                            "trip": trip,
                            "bart_text": opt["text"],
                            "label_rule": opt["label_rule"],
                            # Mock mode: the scripted model echoes the label. Live mode ignores mock_turns.
                            "mock_turns": [
                                {
                                    "type": "tool_use",
                                    "name": "draft_message",
                                    "input": {
                                        "option": label,
                                        "station_abbr": abbr,
                                        "elevator": e["name"],
                                        "steps": [opt["text"]],
                                        "added_minutes": None,
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Plan",
                                    "input": {
                                        "affected": True,
                                        "option": label,
                                        "steps": [opt["text"]],
                                        "added_minutes": None,
                                        "needs_human_decision": False,
                                        "message": opt["text"],
                                    },
                                },
                            ],
                        },
                        "label": label,
                    }
                )
    return cases


def main() -> int:
    cases = build_cases()
    suite = {
        "suite": "policy_agreement",
        "description": (
            "One case per (station, elevator, condition) from kb/stations. Label = the option label "
            "derived from BART's documented text (kb/labels.py). Output is the option the model put in "
            "its Plan before code verification. Mock mode proves plumbing (scripted model echoes the label); "
            "live mode reports the real number and is capped by --max-model-calls."
        ),
        "output_of": "policy_agreement",
        "generated_from": "kb/stations/*.json via evals/gen_policy_cases.py",
        "cases": cases,
    }
    OUT.write_text(json.dumps(suite, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parents[2])}: {len(cases)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
