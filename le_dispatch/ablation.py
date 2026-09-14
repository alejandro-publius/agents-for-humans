"""Gate ablation: remove one gate at a time and count what reaches the rider.

The red team shows that with every gate in place nothing hostile reaches
the rider. That is necessary, not sufficient: a counter that never moves
could be a counter that cannot move, and a gate that never fires could be
dead weight. This study runs the same 140 attacks with each gate switched
off (`build_agent(disabled=...)`), then with the before-tool gates off
together, the after-model gate off, and everything off, and records the
four leak counters and where each attack was caught.

What it is expected to show, and does on the fixture run:

- the after-model gate is the line that protects the rider: remove it and
  fake stations, wrong options, invented minutes and hostile sentences all
  reach the rider, whatever the before-tool gates do
- the approved-sentence check subsumes the prose checks for what reaches
  the rider (remove the prose checks alone and the approval check still
  rejects the sentence); the prose checks stay because their reasons name
  the exact problem, which is what makes the feedback actionable
- the before-tool gates never change what reaches the rider on their own;
  they are the in-process twin of the gateway's Cedar policy and the
  early, specific feedback the convergence study measures

Every configuration also runs a convergence slice (the rule-following
stand-in model, every persona) so the cost of a missing gate in model
calls is on the same table. Fixture run; not a result until the laptop
reruns it on the real KB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .adaptive import run_convergence
from .gates import GATES, build_agent
from .interfaces import Case, KBSet, PolicyCallable, claimable, data_source, source_label, write_results_json
from .red_team import ATTACKS, LEAK_KEYS, RedTeamResult, run_red_team

RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "gate_ablation.json"

CONFIGS: dict[str, frozenset[str]] = {
    "all_gates": frozenset(),
    "without_kb_hook": frozenset({"kb_hook"}),
    "without_option_gate": frozenset({"option_gate"}),
    "without_plan_fields": frozenset({"plan_fields"}),
    "without_plan_prose": frozenset({"plan_prose"}),
    "without_plan_approval": frozenset({"plan_approval"}),
    "without_before_tool_gates": frozenset({"kb_hook", "option_gate"}),
    "without_after_model_gate": frozenset({"plan_fields", "plan_prose", "plan_approval"}),
    "without_any_gate": frozenset(GATES),
}


def leaks_by_attack(result: RedTeamResult) -> dict[str, dict[str, int]]:
    """For each attack kind, how many runs leaked on each counter."""
    out = {kind: {k: 0 for k in LEAK_KEYS} for kind in ATTACKS}
    for r in result.runs:
        for k, leaked in r.leaked.items():
            out[r.kind][k] += 1 if leaked else 0
    return out


def run_ablation(
    kb: KBSet,
    policy: PolicyCallable,
    cases: list[Case],
    *,
    n_per_attack: int = 20,
    configs: dict[str, frozenset[str]] | None = None,
    convergence_cases: int = 6,
) -> dict[str, Any]:
    configs = configs or CONFIGS
    rows: dict[str, Any] = {}
    for name, disabled in configs.items():

        def factory(model: Any, trip: Any, disabled: frozenset[str] = disabled) -> Any:
            return build_agent(model, kb, policy, trip, disabled=disabled)

        red = run_red_team(kb, policy, cases, n_per_attack=n_per_attack, agent_factory=factory)
        counts = red.counts()
        conv = run_convergence(kb, policy, cases[:convergence_cases], disabled=disabled)
        rows[name] = {
            "disabled": sorted(disabled),
            "runs": counts["runs"],
            "reached_rider": counts["reached_rider"],
            "leaked_runs": sum(1 for r in red.runs if any(r.leaked.values())),
            "caught": counts["caught"],
            "plans_delivered": counts["plans_delivered"],
            "composed_by_code": counts["composed_by_code"],
            "leaks_by_attack": {k: v for k, v in leaks_by_attack(red).items() if any(v.values())},
            "convergence": {
                "runs": conv["runs"],
                "converged": conv["converged"],
                "max_calls": conv["max_calls"],
                "mean_calls": _mean_calls(conv),
            },
        }
    return {
        "provenance": {
            "run": f"red team and a convergence slice with gates removed one at a time, {source_label()}",
            "claimable": claimable(),
            "source": data_source(),
            "note": "A study of which gate protects what. Rerun on the laptop with the real KB before citing.",
        },
        "gates": list(GATES),
        "n_per_attack": n_per_attack,
        "configs": rows,
        "summary": summarize(rows),
    }


def _mean_calls(conv: dict[str, Any]) -> float | None:
    total = n = 0
    for p in conv["per_persona"].values():
        if p["mean_calls"] is not None:
            total += p["mean_calls"] * p["converged"]
            n += p["converged"]
    return round(total / n, 2) if n else None


def summarize(rows: dict[str, Any]) -> dict[str, Any]:
    """The sentences the docs quote, derived, never typed."""
    zero = {k: 0 for k in LEAK_KEYS}
    load_bearing = sorted(name for name, r in rows.items() if r["reached_rider"] != zero)
    harmless_alone = sorted(name for name, r in rows.items() if r["reached_rider"] == zero and name != "all_gates")
    return {
        "configs_with_zero_leaks": sorted(name for name, r in rows.items() if r["reached_rider"] == zero),
        "configs_with_leaks": load_bearing,
        "single_gates_whose_removal_leaks_nothing": [
            n for n in harmless_alone if n.startswith("without_") and len(rows[n]["disabled"]) == 1
        ],
        "every_config_delivered_every_plan": all(r["plans_delivered"] == r["runs"] for r in rows.values()),
    }


def write_results(doc: dict[str, Any], path: Path = RESULTS_PATH) -> dict[str, Any]:
    write_results_json(path, doc)
    return doc


def render(doc: dict[str, Any]) -> str:
    keys = ("hallucinated_stations", "wrong_options", "minutes_not_from_policy", "unapproved_messages")
    head = f"{'configuration':28} {'runs':>4}  stations options minutes unapproved  leaked_runs  conv max/mean"
    lines = [f"gate ablation: {doc['n_per_attack']} runs per attack, {len(doc['configs'])} configurations", head]
    for name, r in doc["configs"].items():
        rr = r["reached_rider"]
        c = r["convergence"]
        lines.append(
            f"{name:28} {r['runs']:>4}  {rr[keys[0]]:>8} {rr[keys[1]]:>7} {rr[keys[2]]:>7} {rr[keys[3]]:>10}  "
            f"{r['leaked_runs']:>11}  {c['converged']}/{c['runs']} {c['max_calls']}/{c['mean_calls']}"
        )
    s = doc["summary"]
    lines.append(f"zero leaks: {', '.join(s['configs_with_zero_leaks'])}")
    lines.append(f"leaks: {', '.join(s['configs_with_leaks'])}")
    lines.append(f"every configuration delivered every plan: {s['every_config_delivered_every_plan']}")
    return "\n".join(lines)
