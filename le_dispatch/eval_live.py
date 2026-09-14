"""F7: two-model live eval configuration and the README table generator.

`make eval-live` iterates a model list (the Sonnet inference profile and
Amazon Nova Lite, from evals/live_models.json) times two modes (enforced,
no_steering), 200-call hard cap per entry, and writes four live entries
with model ids into results/policy_agreement.json. The real run happens
on the laptop with Bedrock credentials; here the runner is exercised with
a scripted model factory, and without credentials the script prints the
entries it would run.

The table generator renders any number of rows from
results/policy_agreement.json (mock, live, agentcore-evaluations) for the
README, marking rows that are plumbing proof only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strands.models.model import Model

from .budget import BudgetedModel, BudgetExceeded  # noqa: F401  (re-exported)
from .gates import build_agent, deliver
from .interfaces import Case, KBSet, PolicyCallable, Trip, claimable, data_source
from .interfaces import credentials_present as _credentials_present

ROOT = Path(__file__).resolve().parent.parent
MODELS_PATH = ROOT / "evals" / "live_models.json"
RESULTS_PATH = ROOT / "results" / "policy_agreement.json"


@dataclass
class LiveModel:
    name: str
    provider: str
    model_id: str


def load_models(path: Path = MODELS_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text())
    data["models"] = [LiveModel(**m) for m in data["models"]]
    return data


def credentials_present() -> bool:
    """One implementation for every apply path: see interfaces.credentials_present."""
    return _credentials_present()


def case_trip(case: Case, i: int = 0) -> Trip:
    dest = "EMBR" if case.station != "EMBR" else "MONT"
    return Trip(rider_id=f"eval-{i:03d}", origin=case.station, destination=dest, outages=(case.elevator,))


def run_entry(
    model: LiveModel,
    mode: str,
    cases: list[Case],
    kb: KBSet,
    policy: PolicyCallable,
    *,
    model_factory: Callable[[LiveModel], Model],
    cap: int = 200,
    retry_strategy: Any = None,
) -> dict[str, Any]:
    """One (model, mode) entry over the cases, under the hard cap. Agreement =
    the model's final plan carries the policy engine's top option. Each case
    runs through deliver(): a case where the model never complies (the per-run
    cap, a StructuredOutputException, a provider error) counts as a
    disagreement composed by code, never as a crash of the entry. Only the
    entry-wide cap stops the entry."""
    budget = BudgetedModel(model_factory(model), cap, label=f"{model.name}/{mode}")
    agree = 0
    ran = 0
    composed_by_code = 0
    tokens = 0
    stopped = None
    consecutive_exceptions = 0
    for i, case in enumerate(cases):
        trip = case_trip(case, i)
        decision = policy(trip)
        prompt = (
            f"Plan my trip from {trip.origin} to {trip.destination}. Elevator {case.elevator} at {case.station} "
            f"is out. Use draft_plan, then return the Plan with one of its approved_messages."
        )
        bundle = build_agent(budget, kb, policy, trip, steering=(mode == "enforced"), retry_strategy=retry_strategy)
        out = deliver(bundle, prompt)
        if budget.calls >= cap and out.composed_by != "model":
            stopped = f"{model.name}/{mode}: hard cap of {cap} model calls reached"
            break
        ran += 1
        tokens += int(out.usage.get("total_tokens", 0))
        if out.composed_by == "code":
            composed_by_code += 1
            # a provider that fails on every call (credentials, a wrong model id, a region without the model)
            # would otherwise fill the entry with silent disagreements: three in a row and the entry stops
            consecutive_exceptions = consecutive_exceptions + 1 if out.stop_reason == "exception" else 0
            if consecutive_exceptions >= 3:
                stopped = f"{model.name}/{mode}: three provider errors in a row, last: {out.reason[:200]}"
                break
        else:
            consecutive_exceptions = 0
            if out.plan is not None and out.plan.get("option") == decision.top_option:
                agree += 1
    return {
        "provider": model.provider,
        "model_id": model.model_id,
        "model_name": model.name,
        "mode": mode,
        "cases": ran,
        "cases_planned": len(cases),
        "agree": agree,
        "agreement_pct": round(100.0 * agree / ran, 1) if ran else None,
        "composed_by_code": composed_by_code,
        "calls_used": budget.calls,
        "tokens_used": tokens,  # the price of the mode: enforced retries cost tokens, and the table says how many
        "hard_cap_calls": cap,
        "stopped_early": stopped,
        "source": data_source(),  # what the run read: the fixtures, or the real exports
        "claimable": model.provider != "scripted" and claimable(),  # a live model on fixture cases is not a result
    }


def run_all(
    config: dict[str, Any],
    cases: list[Case],
    kb: KBSet,
    policy: PolicyCallable,
    *,
    model_factory: Callable[[LiveModel], Model],
    retry_strategy: Any = None,
) -> list[dict[str, Any]]:
    cap = int(config.get("hard_cap_calls_per_entry", 200))
    return [
        run_entry(m, mode, cases, kb, policy, model_factory=model_factory, cap=cap, retry_strategy=retry_strategy)
        for m in config["models"]
        for mode in config["modes"]
    ]


def merge_entries(new_entries: list[dict[str, Any]], path: Path = RESULTS_PATH) -> dict[str, Any]:
    """Add or replace rows by (provider, model_id, mode, evaluator); keep everything else."""
    doc = json.loads(path.read_text()) if path.exists() else {"entries": []}

    def key(e: dict[str, Any]) -> tuple:
        return (e.get("provider"), e.get("model_id"), e.get("mode"), e.get("evaluator"))

    new_keys = {key(e) for e in new_entries}
    doc["entries"] = [e for e in doc.get("entries", []) if key(e) not in new_keys] + list(new_entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def planned_entries(config: dict[str, Any]) -> list[str]:
    cap = config.get("hard_cap_calls_per_entry", 200)
    return [
        f"{m.name:<10} {m.model_id:<48} {mode:<12} cap {cap} calls"
        for m in config["models"]
        for mode in config["modes"]
    ]


# README table -----------------------------------------------------------------

HEADERS = ["Provider", "Model", "Mode", "Evaluator", "Cases", "Agreement", "Calls, tokens", "Status"]


def load_entries(path: Path = RESULTS_PATH) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    entries = data["entries"] if isinstance(data, dict) and "entries" in data else data
    if not isinstance(entries, list):
        raise ValueError(f"unrecognized results shape in {path}")
    return entries


def _status(e: dict[str, Any]) -> str:
    if e.get("provider") == "mock":
        return "plumbing proof only" + (", never an ablation result" if e.get("mode") == "no_steering" else "")
    if e.get("provider") == "stand-in":
        return "stand-in client through the real adapter: plumbing proof only, never a result"
    if e.get("claimable") is False:
        if e.get("source", {}).get("fixture") and e.get("cases"):
            return "live model on the fixture cases: rerun on the exports before citing"
        return "pending laptop run"
    status = "stopped at hard cap" if e.get("stopped_early") else "live"
    if e.get("composed_by_code"):
        status += f", {e['composed_by_code']} plan(s) composed by code"
    return status


def render_row(e: dict[str, Any]) -> str:
    pct = e.get("agreement_pct")
    pct_s = f"{pct:.1f}%" if isinstance(pct, (int, float)) else "TODO"
    cases = e.get("cases") if e.get("cases") is not None else "TODO"
    calls, tokens = e.get("calls_used"), e.get("tokens_used")
    cost = (f"{calls}, {tokens:,}" if isinstance(tokens, int) else f"{calls}, n/a") if calls is not None else "n/a"
    return (
        f"| {e.get('provider', '?')} | `{e.get('model_id', '?')}` | {e.get('mode', '?')} | "
        f"{e.get('evaluator', 'local option equality')} | {cases} | {pct_s} | {cost} | {_status(e)} |"
    )


def render_table(entries: list[dict[str, Any]]) -> str:
    lines = ["| " + " | ".join(HEADERS) + " |", "|" + "|".join("---" for _ in HEADERS) + "|"]
    lines.extend(render_row(e) for e in entries)
    return "\n".join(lines)


def render_readme_section(entries: list[dict[str, Any]]) -> str:
    live = [e for e in entries if e.get("provider") not in ("mock",) and e.get("claimable") is not False]
    intro = (
        "Policy agreement: does the plan that reaches the rider carry the KB label? "
        "Enforced runs the two-stage gate; no_steering removes the steering handler and keeps the hook. "
        f"Rows: {len(entries)} ({len(live)} live). Numbers come from `results/policy_agreement.json` "
        "and are checked by `make verify`."
    )
    return intro + "\n\n" + render_table(entries)
