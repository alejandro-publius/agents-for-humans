"""A5. Disabling the hook and the steering handler changes the eval results."""

import json

from evals import run as evals_run


def _flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flat(v, key))
        else:
            out[key] = v
    return out


def test_ablation_differs_from_full_run(tmp_path):
    assert evals_run.main(["--out", str(tmp_path)]) == 0
    assert evals_run.main(["--ablate", "--out", str(tmp_path)]) == 0
    full = json.loads((tmp_path / "summary.json").read_text())
    ablated = json.loads((tmp_path / "ablation.json").read_text())

    assert full["ablated"] is False and ablated["ablated"] is True
    assert full["cases_run"] == ablated["cases_run"], "same cases in both runs"
    # The guardrails are what make these cases pass; without them the harness suites fail.
    assert full["hook_cancellations"] > 0 and ablated["hook_cancellations"] == 0
    assert full["steering_rewrites"] > 0 and ablated["steering_rewrites"] == 0
    assert ablated["cases_passed"] < full["cases_passed"]

    fa, fb = _flat(full), _flat(ablated)
    differing = [k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k)]
    assert differing, "ablation must change at least one field"
