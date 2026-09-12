"""Evals harness. ``make evals`` (mock provider, offline, $0) or ``make evals ABLATE=1``.

Loads every suite in ``evals/cases/*.json``, runs each case through the agent, scores it with
Strands Evals (``strands_evals.Experiment`` + the deterministic ``Equals`` evaluator), and writes
``results/summary.json`` plus one file per suite, or ``results/ablation.json`` when ``--ablate``.

Exit codes: 0 ok; 2 a case is missing its ``label``; 3 the mock run touched the network.

Honesty: on the mock provider these suites measure the harness (hook, steering, schema), not
model quality. ``summary.json`` says which provider ran.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from strands.models.bedrock import DEFAULT_BEDROCK_MODEL_ID  # noqa: E402
from strands_evals import Case, Experiment  # noqa: E402
from strands_evals.evaluators import Equals  # noqa: E402

from agent.core import AgentConfig, BuiltAgent, build_agent  # noqa: E402
from agent.counting_model import BudgetExhausted, CallBudget, CountingModel  # noqa: E402
from agent.envfile import load_env_file  # noqa: E402
from agent.mock_model import MockModel  # noqa: E402
from agent.outage_parser import parse_and_validate  # noqa: E402
from agent.run import run_condition  # noqa: E402
from agent.steering import first_option_mentioned  # noqa: E402
from agent.tools import draft_message, plan_alternatives  # noqa: E402
from policy import Trip  # noqa: E402
from policy.sun import PACIFIC  # noqa: E402

CASES_DIR = REPO_ROOT / "evals" / "cases"
RESULTS_DIR = REPO_ROOT / "results"


class MissingLabel(SystemExit):
    pass


# --- network guard for the mock provider -------------------------------------------------------
class _Guard:
    attempts = 0


def install_network_guard() -> None:
    def refuse(*args: Any, **kwargs: Any):
        _Guard.attempts += 1
        raise ConnectionError("network disabled: mock provider run")

    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.create_connection = refuse  # type: ignore[assignment]
    socket.getaddrinfo = refuse  # type: ignore[assignment]


# --- suites ------------------------------------------------------------------------------------
def load_suites(only: list[str] | None = None) -> list[dict[str, Any]]:
    suites = []
    for path in sorted(CASES_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        data.setdefault("suite", path.stem)
        if only and data["suite"] not in only:
            continue
        for case in data["cases"]:
            if "label" not in case:
                raise MissingLabel(f"case {case.get('name')!r} in {path.name} has no label")
        suites.append(data)
    return suites


def canonical(value: Any) -> Any:
    """Dict labels are compared as sorted JSON so the Equals evaluator sees plain strings."""
    return json.dumps(value, sort_keys=True) if isinstance(value, dict) else value


def bedrock_credentials_present() -> bool:
    cred_vars = ("AWS_ACCESS_KEY_ID", "AWS_BEARER_TOKEN_BEDROCK", "AWS_PROFILE")
    return bool(os.getenv("AWS_REGION") and any(os.getenv(v) for v in cred_vars))


def make_model(provider: str, case_input: dict[str, Any], budget: CallBudget | None = None):
    if provider == "mock":
        if "mock_turns" in case_input:
            return MockModel(case_input["mock_turns"], name=case_input.get("name", "inline"))
        return MockModel.from_fixture(case_input["model_fixture"])
    if provider == "bedrock":
        if not bedrock_credentials_present():
            raise SystemExit("bedrock provider requested but AWS_REGION and credentials are not set")
        from strands.models import BedrockModel

        model_id = os.getenv("EVAL_MODEL_ID")
        extra = {"model_id": model_id} if model_id else {}
        inner = BedrockModel(region_name=os.environ["AWS_REGION"], **extra)
        return CountingModel(inner, budget or CallBudget(cap=10**9), name=case_input.get("name", "live"))
    raise SystemExit(f"unknown provider {provider!r}")


def run_case(case_input: dict[str, Any], *, provider: str, ablate: bool) -> tuple[BuiltAgent, Any]:
    kwargs = {
        "required_option": case_input.get("required_option"),
        "structured_output": case_input.get("structured_output", True),
    }
    config = AgentConfig.ablated(**kwargs) if ablate else AgentConfig(**kwargs)
    built = build_agent(make_model(provider, case_input), config=config)
    result = built(case_input["prompt"])
    return built, result


def extract_output(kind: str, built: BuiltAgent, result: Any) -> str:
    if kind == "first_tool_status":
        for message in built.agent.messages:
            for block in message.get("content", []):
                if "toolResult" in block:
                    text = " ".join(c.get("text", "") for c in block["toolResult"].get("content", []))
                    return "cancelled" if "CANCELLED" in text else "executed"
        return "no_tool_call"
    if kind == "first_option_in_text":
        return first_option_mentioned(str(result)) or "none"
    if kind == "plan_option":
        plan = getattr(result, "structured_output", None)
        return plan.option if plan is not None else "no_plan"
    raise SystemExit(f"unknown output_of {kind!r}")


EVAL_WHEN = datetime(2026, 9, 12, 8, 0, tzinfo=PACIFIC)  # daytime, so documented options are feasible
LIVE_ENV_NAMES = (
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_PROFILE",
    "EVAL_MODEL_ID",
)


POLICY_FILE = "policy_agreement.json"
POLICY_MOCK_FILE = "policy_agreement.mock.json"


def model_slug(model_id: str | None) -> str:
    """'us.amazon.nova-lite-v1:0' -> 'us-amazon-nova-lite-v1-0'; empty for the default model."""
    if not model_id:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", model_id.lower()).strip("-")


def entry_name(variant: str, model_id: str | None) -> str:
    """Entry key in results/policy_agreement.json: 'enforced' for the default model, else with a slug."""
    slug = model_slug(model_id)
    return f"{variant}-{slug}" if slug else variant


def read_policy_file(out_dir: Path, name: str = POLICY_FILE) -> dict[str, Any]:
    path = out_dir / name
    return json.loads(path.read_text()) if path.exists() else {"suite": "policy_agreement"}


def frozen_live_result(out_dir: Path, entry: str | None = None) -> dict[str, Any] | None:
    """A frozen live entry ('enforced' or 'no_steering') in results/policy_agreement.json, if any."""
    data = read_policy_file(out_dir)
    names = [entry] if entry else [k for k, v in data.items() if isinstance(v, dict) and "mode" in v]
    for name in names:
        e = data.get(name)
        if isinstance(e, dict) and e.get("frozen") and e.get("mode") != "mock":
            return e
    return None


def merge_policy_entry(out_dir: Path, name: str, entry: str, result: dict[str, Any]) -> None:
    """Write one variant's result next to the other's; the two entries are independent."""
    data = read_policy_file(out_dir, name)
    data[entry] = result
    data["frozen"] = any(isinstance(v, dict) and v.get("frozen") for v in data.values())
    (out_dir / name).write_text(json.dumps(data, indent=2) + "\n")


def git_describe() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


POLICY_VARIANTS = {
    # enforced: the wired agent as shipped (steering on, all three tools)
    "enforced": {"steering": True, "tools": None},
    # no_steering: the model's unaided choice: no steering handler, no get_station_facts tool
    "no_steering": {"steering": False, "tools": [plan_alternatives, draft_message]},
}


def variant_tool_names(spec: dict[str, Any]) -> list[str]:
    if spec["tools"]:
        return [t.tool_name for t in spec["tools"]]
    return ["get_station_facts", "plan_alternatives", "draft_message"]


def run_suite(
    suite: dict[str, Any],
    *,
    provider: str,
    ablate: bool,
    max_model_calls: int | None = None,
    variant: str = "enforced",
) -> dict[str, Any]:
    kind = suite["output_of"]
    spec = POLICY_VARIANTS[variant]
    mechanisms = {"hook_cancellations": 0, "steering_rewrites": 0, "steering_guides": 0, "model_calls": 0}
    details: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    budget = CallBudget(cap=max_model_calls) if (max_model_calls and provider != "mock") else None

    def task(case: Case) -> Any:
        if kind == "policy_agreement":
            if budget is not None and budget.exhausted:
                skipped.append(case.name)
                details[case.name] = {"expected": labels[case.name], "actual": None, "skipped": "budget"}
                return "__skipped__"
            inp = case.input
            model = make_model(provider, {**inp, "name": case.name}, budget)
            trip = Trip(origin=inp["trip"]["origin"], dest=inp["trip"]["dest"])
            cfg = AgentConfig(steering_enabled=spec["steering"])
            try:
                report = run_condition(
                    trip,
                    inp["station"],
                    inp["elevator"],
                    inp["situation"],
                    EVAL_WHEN,
                    model,
                    config=cfg,
                    tools=spec["tools"],
                )
            except BudgetExhausted:
                skipped.append(case.name)
                mechanisms["model_calls"] += len(model.calls)
                details[case.name] = {"expected": labels[case.name], "actual": None, "skipped": "budget"}
                return "__skipped__"
            mechanisms["model_calls"] += report.mechanisms.get("model_calls", 0)
            mechanisms["hook_cancellations"] += report.mechanisms.get("hook_cancellations", 0)
            mechanisms["steering_guides"] += report.mechanisms.get("steering_guides", 0)
            model_option = report.model_plan["option"] if report.model_plan else None
            details[case.name] = {
                "expected": labels[case.name],
                "actual": model_option,
                "final_after_code": report.final_plan["option"] if report.final_plan else None,
                "policy_top": report.decision.get("top_option"),
                "label_rule": inp["label_rule"],
                "error": report.error,
            }
            return model_option
        if kind == "outage_parse":
            fragment = case.input["fragment"]
            model = make_model(provider, {**case.input, "name": case.name})
            actual = parse_and_validate(fragment, model).as_label()
            mechanisms["model_calls"] += len(getattr(model, "calls", [])) or 1
            baseline = parse_and_validate(fragment).as_label()
            details[case.name] = {
                "expected": labels[case.name],
                "actual": actual,
                "regex_baseline": baseline,
            }
            return canonical(actual)
        built, result = run_case(case.input, provider=provider, ablate=ablate)
        actual = extract_output(kind, built, result)
        if built.validator_hook:
            mechanisms["hook_cancellations"] += len(built.validator_hook.cancelled)
        if built.steering:
            mechanisms["steering_rewrites"] += len(built.steering.rewrites)
        model = built.agent.model
        mechanisms["model_calls"] += len(getattr(model, "calls", [])) or 1
        details[case.name] = {"expected": case.expected_output, "actual": actual}
        return actual

    labels = {c["name"]: c["label"] for c in suite["cases"]}
    cases = [
        Case(name=c["name"], input=c["input"], expected_output=canonical(c["label"])) for c in suite["cases"]
    ]
    report = Experiment(cases=cases, evaluators=[Equals()]).run_evaluations(task)

    passes = [bool(p) for p in report.test_passes]
    for name, ok in zip(details, passes, strict=True):
        details[name]["pass"] = ok and not details[name].get("skipped")
    cases_run = len(cases) - len(skipped)
    passed = sum(1 for name in details if details[name]["pass"])
    baselines: dict[str, Any] = {}
    if kind == "policy_agreement":
        cases_run = len(cases) - len(skipped)
        by_label: dict[str, dict[str, int]] = {}
        for d in details.values():
            if d.get("skipped"):
                continue
            row = by_label.setdefault(d["expected"], {"cases": 0, "agree": 0})
            row["cases"] += 1
            row["agree"] += int(d["actual"] == d["expected"])
        baselines["by_label"] = by_label
        baselines["cases_skipped_for_budget"] = len(skipped)
        code_agree = sum(1 for d in details.values() if d.get("final_after_code") == d["expected"])
        code_pct = round(100.0 * code_agree / cases_run, 1) if cases_run else None
        baselines["final_after_code_agreement_pct"] = code_pct
    if kind == "outage_parse":
        regex_ok = sum(1 for d in details.values() if d["regex_baseline"] == d["expected"])
        baselines["regex_accuracy_pct"] = round(100.0 * regex_ok / cases_run, 1) if cases_run else None
        baselines["regex_cases_passed"] = regex_ok
    return {
        "baselines": baselines,
        "mode": provider,
        "variant": variant if kind == "policy_agreement" else None,
        "steering": spec["steering"] if kind == "policy_agreement" else None,
        "tools": variant_tool_names(spec) if kind == "policy_agreement" else None,
        "agreement_pct": round(100.0 * passed / cases_run, 1) if cases_run else None,
        "model_call_budget": max_model_calls if provider != "mock" else None,
        "suite": suite["suite"],
        "description": suite["description"],
        "output_of": kind,
        "cases_run": cases_run,
        "cases_passed": passed,
        "accuracy": round(passed / cases_run, 4) if cases_run else None,
        "accuracy_pct": round(100.0 * passed / cases_run, 1) if cases_run else None,
        "strands_evals_overall_score": report.overall_score,
        "mechanisms": mechanisms,
        "cases": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--provider", choices=["mock", "bedrock"], default="mock")
    parser.add_argument("--ablate", action="store_true", help="disable the hook and the steering handler")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--max-model-calls", type=int, default=200, help="live providers only: hard cap on model calls"
    )
    parser.add_argument("--suite", action="append", help="run only this suite (repeatable)")
    parser.add_argument("--env-file", type=Path, help="load AWS_* / EVAL_MODEL_ID from this KEY=value file")
    parser.add_argument(
        "--force-live", action="store_true", help="overwrite a frozen live policy_agreement result"
    )
    parser.add_argument(
        "--no-steering",
        action="store_true",
        help="policy_agreement ablation: no steering handler, no get_station_facts (unaided choice)",
    )
    args = parser.parse_args(argv)
    variant = "no_steering" if args.no_steering else "enforced"
    if args.no_steering:
        args.suite = ["policy_agreement"]
    if args.env_file:
        load_env_file(args.env_file, LIVE_ENV_NAMES)
    entry = entry_name(variant, os.getenv("EVAL_MODEL_ID") if args.provider != "mock" else None)

    if args.provider == "mock":
        install_network_guard()
    elif args.ablate:
        print("evals: --ablate runs on the mock provider only (no spend on ablations)", file=sys.stderr)
        return 2
    elif not args.force_live and frozen_live_result(args.out, entry) is not None:
        msg = f"evals: policy_agreement.json has a frozen live '{entry}' entry; pass --force-live"
        print(msg, file=sys.stderr)
        return 4

    try:
        suites = load_suites(args.suite)
    except MissingLabel as exc:
        print(f"evals: {exc}", file=sys.stderr)
        return 2
    if not suites:
        print(f"evals: no suites matched {args.suite}", file=sys.stderr)
        return 2

    suite_results = [
        run_suite(
            s,
            provider=args.provider,
            ablate=args.ablate,
            max_model_calls=args.max_model_calls,
            variant=variant,
        )
        for s in suites
    ]
    cases_run = sum(r["cases_run"] for r in suite_results)
    cases_passed = sum(r["cases_passed"] for r in suite_results)
    summary = {
        "provider": args.provider,
        "ablated": args.ablate,
        "note": (
            "mock provider: scripted model turns from fixtures/model; these suites measure the harness "
            "(hook, steering, schema), not model quality"
            if args.provider == "mock"
            else "live model provider"
        ),
        "network_attempts": _Guard.attempts,
        "cases_run": cases_run,
        "cases_passed": cases_passed,
        "accuracy": round(cases_passed / cases_run, 4) if cases_run else None,
        "accuracy_pct": round(100.0 * cases_passed / cases_run, 1) if cases_run else None,
        "hook_cancellations": sum(r["mechanisms"]["hook_cancellations"] for r in suite_results),
        "steering_rewrites": sum(r["mechanisms"]["steering_rewrites"] for r in suite_results),
        "model_calls": sum(r["mechanisms"]["model_calls"] for r in suite_results),
        "suites": {r["suite"]: r for r in suite_results},
    }

    args.out.mkdir(parents=True, exist_ok=True)
    if args.ablate:
        (args.out / "ablation.json").write_text(json.dumps(summary, indent=2) + "\n")
        written = ["ablation.json"]
    elif args.provider != "mock":
        # A live run writes only its own entry, stamped frozen; summary.json stays the mock harness.
        written = []
        for r in suite_results:
            r["frozen"] = True
            r["provider"] = "bedrock"
            r["run_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            r["model_id"] = os.getenv("EVAL_MODEL_ID") or DEFAULT_BEDROCK_MODEL_ID
            r["labels_git"] = git_describe()
            if r["suite"] == "policy_agreement":
                merge_policy_entry(args.out, POLICY_FILE, entry, r)
                written.append(f"{POLICY_FILE}[{entry}]")
            else:
                (args.out / f"{r['suite']}.json").write_text(json.dumps(r, indent=2) + "\n")
                written.append(f"{r['suite']}.json")
    else:
        written = []
        if not args.no_steering:
            (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            written.append("summary.json")
        for r in suite_results:
            if r["suite"] == "policy_agreement":
                r["provider"] = "mock"
                # never overwrite a frozen live entry: shadow the whole file instead
                name = POLICY_MOCK_FILE if frozen_live_result(args.out) is not None else POLICY_FILE
                merge_policy_entry(args.out, name, variant, r)
                written.append(f"{name}[{variant}]")
            else:
                (args.out / f"{r['suite']}.json").write_text(json.dumps(r, indent=2) + "\n")
                written.append(f"{r['suite']}.json")

    tag = "ABLATED" if args.ablate else "full"
    for r in suite_results:
        print(f"{tag:8} {r['suite']:22} {r['cases_passed']}/{r['cases_run']} passed  {r['mechanisms']}")
        if r["suite"] == "policy_agreement":
            print(
                f"{tag:8} policy_agreement[{variant}]: agreement {r['agreement_pct']}% on {r['cases_run']} "
                f"cases (mode={r['mode']}, steering={r['steering']}, tools={r['tools']}, "
                f"skipped for budget={r['baselines']['cases_skipped_for_budget']}, "
                f"steering guides={r['mechanisms']['steering_guides']})"
            )
        if r["suite"] == "outage_parse":
            print(
                f"{tag:8} outage_parse accuracy: {r['accuracy_pct']}% on {r['cases_run']} cases "
                f"({args.provider} provider); regex baseline {r['baselines']['regex_accuracy_pct']}%"
            )
    print(
        f"{tag:8} total {cases_passed}/{cases_run} passed, "
        f"network_attempts={_Guard.attempts}, wrote {written}"
    )
    if args.provider == "mock" and _Guard.attempts:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
