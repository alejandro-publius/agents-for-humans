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
import socket
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from strands_evals import Case, Experiment  # noqa: E402
from strands_evals.evaluators import Equals  # noqa: E402

from agent.core import AgentConfig, BuiltAgent, build_agent  # noqa: E402
from agent.mock_model import MockModel  # noqa: E402
from agent.outage_parser import parse_and_validate  # noqa: E402
from agent.steering import first_option_mentioned  # noqa: E402

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
def load_suites() -> list[dict[str, Any]]:
    suites = []
    for path in sorted(CASES_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        data.setdefault("suite", path.stem)
        for case in data["cases"]:
            if "label" not in case:
                raise MissingLabel(f"case {case.get('name')!r} in {path.name} has no label")
        suites.append(data)
    return suites


def canonical(value: Any) -> Any:
    """Dict labels are compared as sorted JSON so the Equals evaluator sees plain strings."""
    return json.dumps(value, sort_keys=True) if isinstance(value, dict) else value


def make_model(provider: str, case_input: dict[str, Any]):
    if provider == "mock":
        if "mock_turns" in case_input:
            return MockModel(case_input["mock_turns"], name=case_input.get("name", "inline"))
        return MockModel.from_fixture(case_input["model_fixture"])
    if provider == "bedrock":
        has_creds = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_BEARER_TOKEN_BEDROCK")
        if not (os.getenv("AWS_REGION") and has_creds):
            raise SystemExit("bedrock provider requested but AWS_REGION and credentials are not set")
        from strands.models import BedrockModel

        return BedrockModel(region_name=os.environ["AWS_REGION"])
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


def run_suite(suite: dict[str, Any], *, provider: str, ablate: bool) -> dict[str, Any]:
    kind = suite["output_of"]
    mechanisms = {"hook_cancellations": 0, "steering_rewrites": 0, "model_calls": 0}
    details: dict[str, dict[str, Any]] = {}

    def task(case: Case) -> Any:
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
        details[name]["pass"] = ok
    cases_run = len(cases)
    passed = sum(passes)
    baselines: dict[str, Any] = {}
    if kind == "outage_parse":
        regex_ok = sum(1 for d in details.values() if d["regex_baseline"] == d["expected"])
        baselines["regex_accuracy_pct"] = round(100.0 * regex_ok / cases_run, 1) if cases_run else None
        baselines["regex_cases_passed"] = regex_ok
    return {
        "baselines": baselines,
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
    args = parser.parse_args(argv)

    if args.provider == "mock":
        install_network_guard()

    try:
        suites = load_suites()
    except MissingLabel as exc:
        print(f"evals: {exc}", file=sys.stderr)
        return 2

    suite_results = [run_suite(s, provider=args.provider, ablate=args.ablate) for s in suites]
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
    else:
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        written = ["summary.json"]
        for r in suite_results:
            (args.out / f"{r['suite']}.json").write_text(json.dumps(r, indent=2) + "\n")
            written.append(f"{r['suite']}.json")

    tag = "ABLATED" if args.ablate else "full"
    for r in suite_results:
        print(f"{tag:8} {r['suite']:22} {r['cases_passed']}/{r['cases_run']} passed  {r['mechanisms']}")
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
