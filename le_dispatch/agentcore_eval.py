"""F6: AgentCore Evaluations scaffold. No AWS calls from the dispatch session.

Amazon Bedrock AgentCore Evaluations (GA March 31, 2026) offers online
evaluation of sampled traces and on-demand evaluation for programmatic
testing and CI/CD gates, with built-in evaluators, ground-truth datasets
and custom evaluators (prompt, model, or code as a Lambda).

What ships here:
- export_dataset: the 194 frozen cases as a ground-truth dataset in the
  documented on-demand dataset schema (developer guide,
  dataset-evaluations-schema): {"scenarios": [{scenario_id, turns:
  [{input, expected_response}], expected_trajectory, assertions, metadata}]}
- evaluators.json: the built-in tool-selection evaluator
  (Builtin.ToolSelectionAccuracy, tool-call level) alongside
  Builtin.TrajectoryExactOrderMatch (uses expected_trajectory),
  Builtin.Correctness (uses expected_response) and the custom
  option-equality evaluator (code-based, Lambda ARN placeholder).
- plan(): the calls `make agentcore-eval --apply` would make, printed by
  --dry-run with dataset statistics. Data plane client `bedrock-agentcore`:
  invoke_agent_runtime per scenario, then evaluate(evaluatorId,
  evaluationInput={"sessionSpans": ...}, evaluationReferenceInputs=[...]);
  control plane `bedrock-agentcore-control`: create_evaluator for the
  custom evaluator. The starter toolkit's OnDemandEvaluationDatasetRunner
  wraps the same loop; the runbook names both.
- write_scores: stores AgentCore's returned scores in
  results/policy_agreement.json under provider "agentcore-evaluations",
  next to the local entries, never overwriting them.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .interfaces import (
    Case,
    KBSet,
    PolicyCallable,
    Trip,
    data_source,
    runtime_session_id,
    source_label,
    write_results_json,
)
from .interfaces import credentials_present as _credentials_present

ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = ROOT / "evals" / "agentcore"
DATASET_PATH = EVALS_DIR / "dataset.json"
EVALUATORS_PATH = EVALS_DIR / "evaluators.json"
RESULTS_STATS_PATH = ROOT / "results" / "agentcore_dataset.json"
POLICY_AGREEMENT_PATH = ROOT / "results" / "policy_agreement.json"
DEFAULT_REGION = "us-west-2"
PROVIDER = "agentcore-evaluations"

BUILTIN_EVALUATORS = [
    {
        "evaluator_id": "Builtin.ToolSelectionAccuracy",
        "level": "TOOL_CALL",
        "ground_truth": None,
        "why": "was calling draft_plan at that point justified",
    },
    {
        "evaluator_id": "Builtin.TrajectoryExactOrderMatch",
        "level": "SESSION",
        "ground_truth": "expected_trajectory",
        "why": "the tool sequence is exactly draft_plan then the Plan",
    },
    {
        "evaluator_id": "Builtin.Correctness",
        "level": "TRACE",
        "ground_truth": "turns[].expected_response",
        "why": "the response states the KB label",
    },
]
CUSTOM_EVALUATOR = {
    "evaluator_name": "LastElevatorOptionEquality",
    "level": "TRACE",
    "code": "le_dispatch/evaluators/option_equality.py",
    "handler": "option_equality.lambda_handler",
    "lambda_arn": "${OPTION_EQUALITY_LAMBDA_ARN}",
    "lambda_timeout_seconds": 60,
    "ground_truth": "evaluationReferenceInputs[0].expected_option (from scenario metadata.expected_option)",
    "verified_on": "real Strands spans via make agentcore-eval-local (results/agentcore_eval_local.json)",
}
LOCAL_RESULTS_PATH = ROOT / "results" / "agentcore_eval_local.json"

IAM_PERMISSIONS = [
    "bedrock-agentcore:CreateEvaluator",
    "bedrock-agentcore:GetEvaluator",
    "bedrock-agentcore:ListEvaluators",
    "bedrock-agentcore:InvokeAgentRuntime",
    "bedrock-agentcore:Evaluate",
    "lambda:InvokeFunction and lambda:GetFunction on the option-equality Lambda (evaluator execution role)",
    "lambda:CreateFunction, iam:PassRole (to deploy the Lambda once)",
]


def case_trip(case: Case, i: int = 0) -> Trip:
    """The trip a case stands for: the case's elevator is out at its station."""
    dest = "EMBR" if case.station != "EMBR" else "MONT"
    return Trip(rider_id=f"eval-{i:03d}", origin=case.station, destination=dest, outages=(case.elevator,))


def scenario_payload(case: Case, i: int = 0) -> dict[str, Any]:
    """The runtime payload the scenario stands for (the same contract as the poller's)."""
    trip = case_trip(case, i)
    return {
        "rider_id": trip.rider_id,
        "origin": trip.origin,
        "destination": trip.destination,
        "outages": list(trip.outages),
    }


def scenario_input(case: Case, i: int = 0) -> str:
    """The turn's input: the runtime payload as JSON text, so the on-demand runner can hand it to the
    deployed agent unchanged (the entrypoint accepts a payload, or {"prompt": <this text>}), followed by
    the sentence a reader expects. The entrypoint reads the JSON object and ignores the sentence."""
    payload = json.dumps(scenario_payload(case, i))
    return (
        f"{payload} "
        f"A rider's saved trip is affected: elevator {case.elevator} at {case.station} is out. "
        f'BART\'s station page lists this option among others: "{case.option_text}" '
        f"Draft the plan with draft_plan and return the Plan with BART's top option for this outage."
    )


def export_dataset(cases: list[Case], kb: KBSet, policy: PolicyCallable) -> dict[str, Any]:
    """One scenario per frozen case. The ground truth is what code decides for
    the case's trip: the policy engine's top feasible option and its minutes.
    The case's own label stays in metadata (case_label); two cases at the same
    elevator show different option texts and expect the same top option, which
    tests that a lower-ranked option text on the page does not distract the agent."""
    scenarios = []
    for i, c in enumerate(cases):
        d = policy(case_trip(c, i))
        top = d.top_option or c.label
        minutes = d.minutes_for(top)
        scenarios.append(
            {
                "scenario_id": c.case_id,
                "turns": [
                    {
                        "input": scenario_input(c, i),
                        # what a judge compares the agent's response with: the whole plan in one sentence,
                        # since the deployed agent answers with the plan as JSON, not with a label
                        "expected_response": (
                            f"A plan for elevator {c.elevator} at {c.station} with option {top}"
                            + (f" and {minutes} added minutes" if minutes is not None else "")
                            + ", sent to the rider as one of the approved sentences."
                        ),
                    }
                ],
                "expected_trajectory": ["draft_plan", "Plan"],
                "assertions": [
                    f"The plan's option label is {top}",
                    f"The plan names station {c.station} and elevator {c.elevator}",
                    f"The plan's added minutes are {minutes}, copied from the policy engine",
                ],
                "metadata": {
                    "station": c.station,
                    "elevator": c.elevator,
                    "expected_option": top,
                    "added_minutes": minutes,
                    "case_label": c.label,
                    "source_url": c.source_url,
                    "kb_frozen_tag": kb.frozen_tag,
                },
            }
        )
    return {"scenarios": scenarios}


def dataset_stats(dataset: dict[str, Any]) -> dict[str, Any]:
    scenarios = dataset["scenarios"]
    labels = Counter(s["metadata"]["case_label"] for s in scenarios)
    expected = Counter(s["metadata"]["expected_option"] for s in scenarios)
    return {
        "scenarios": len(scenarios),
        "labels": dict(sorted(labels.items())),
        "expected_options": dict(sorted(expected.items())),
        "stations": len({s["metadata"]["station"] for s in scenarios}),
        "elevators": len({s["metadata"]["elevator"] for s in scenarios}),
        "turns_per_scenario": 1,
        "expected_trajectory": scenarios[0]["expected_trajectory"] if scenarios else [],
    }


def evaluators_config() -> dict[str, Any]:
    return {"builtin": BUILTIN_EVALUATORS, "custom": [CUSTOM_EVALUATOR], "region": DEFAULT_REGION}


def write_exports(
    cases: list[Case],
    kb: KBSet,
    policy: PolicyCallable,
    evals_dir: Path = EVALS_DIR,
    stats_path: Path = RESULTS_STATS_PATH,
):
    evals_dir.mkdir(parents=True, exist_ok=True)
    dataset = export_dataset(cases, kb, policy)
    (evals_dir / "dataset.json").write_text(json.dumps(dataset, indent=2) + "\n")
    (evals_dir / "evaluators.json").write_text(json.dumps(evaluators_config(), indent=2) + "\n")
    stats = {
        "provenance": {
            "run": "exporter over the cases JSON",
            "claimable": False,
            "source": data_source(),
            "note": "Dataset statistics only; no evaluation has run. Regenerate from the kb-labels-v1 export.",
            "kb_frozen_tag": kb.frozen_tag,
        },
        **dataset_stats(dataset),
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2) + "\n")
    return dataset, stats


def credentials_present() -> bool:
    """One implementation for every apply path: see interfaces.credentials_present."""
    return _credentials_present()


@dataclass
class EvalPlan:
    region: str
    agent_runtime_arn: str
    dataset_stats: dict[str, Any]
    evaluators: dict[str, Any]
    calls: list[str] = field(default_factory=list)
    iam: list[str] = field(default_factory=lambda: list(IAM_PERMISSIONS))
    api_calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def render(self) -> str:
        s = self.dataset_stats
        lines = [
            f"AgentCore Evaluations plan (region {self.region}); nothing below has been executed",
            "",
            f"dataset: {s['scenarios']} scenarios, labels {s['labels']}, {s['stations']} stations, "
            f"{s['elevators']} elevators, {s['turns_per_scenario']} turn each, expected trajectory "
            f"{s['expected_trajectory']}",
            f"agent runtime: {self.agent_runtime_arn}",
            "",
            "evaluators:",
        ]
        for e in self.evaluators["builtin"]:
            lines.append(f"  {e['evaluator_id']:<36} level {e['level']:<9} ground truth {e['ground_truth']}")
        for e in self.evaluators["custom"]:
            lines.append(
                f"  {e['evaluator_name']:<36} level {e['level']:<9} code {e['code']} (Lambda {e['lambda_arn']})"
            )
        lines += ["", "calls it would make:"]
        lines.extend(f"  {c}" for c in self.calls)
        lines += ["", "IAM permissions needed:"]
        lines.extend(f"  - {p}" for p in self.iam)
        return "\n".join(lines)


def plan(
    dataset: dict[str, Any],
    *,
    region: str = DEFAULT_REGION,
    agent_runtime_arn: str = "${AGENT_RUNTIME_ARN}",
    model_id: str = "${MODEL_ID}",
) -> EvalPlan:
    stats = dataset_stats(dataset)
    n = stats["scenarios"]
    ev = evaluators_config()
    dp = "bedrock-agentcore"
    calls = [
        "bedrock-agentcore-control.create_evaluator(evaluatorName='LastElevatorOptionEquality', level='TRACE', "
        "evaluatorConfig={'codeBased': {'lambdaConfig': {'lambdaArn': ..., 'lambdaTimeoutInSeconds': 60}}}) x1",
        f"{dp}.invoke_agent_runtime(agentRuntimeArn=..., runtimeSessionId=<scenario>, payload=<turn input>) x{n}",
        f"{dp}.evaluate(evaluatorId='Builtin.ToolSelectionAccuracy', evaluationInput={{'sessionSpans': ...}}) x{n}",
        f"{dp}.evaluate(evaluatorId='Builtin.TrajectoryExactOrderMatch', ..., "
        f"evaluationReferenceInputs=[expected_trajectory]) x{n}",
        f"{dp}.evaluate(evaluatorId='Builtin.Correctness', ..., evaluationReferenceInputs=[expected_response]) x{n}",
        f"{dp}.evaluate(evaluatorId=<custom evaluator id>, ..., evaluationReferenceInputs=[expectedResponse, "
        f"assertions, expectedTrajectory]) x{n}  (the evaluator reads the expected option out of them)",
        f"  (or: OnDemandEvaluationDatasetRunner.run() from the starter toolkit, which wraps the invoke, wait, "
        f"collect, evaluate loop) for model {model_id}",
    ]
    first = dataset["scenarios"][0] if dataset.get("scenarios") else None
    return EvalPlan(
        region=region,
        agent_runtime_arn=agent_runtime_arn,
        dataset_stats=stats,
        evaluators=ev,
        calls=calls,
        api_calls=api_calls(first, agent_runtime_arn=agent_runtime_arn),
    )


def reference_inputs(scenario: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    """The scenario's ground truth in the shape the Evaluate API takes (evaluationReferenceInputs): the
    expected response as text, the assertions as text, the expected trajectory as tool names. The custom
    evaluator reads the expected option back out of the expected response and the assertions."""
    turn = scenario["turns"][0]
    return [
        {
            "context": {"spanContext": {"sessionId": session_id}},
            "expectedResponse": {"text": turn["expected_response"]},
            "assertions": [{"text": a} for a in scenario.get("assertions", [])],
            "expectedTrajectory": {"toolNames": list(scenario.get("expected_trajectory", []))},
        }
    ]


def api_calls(
    scenario: dict[str, Any] | None, *, agent_runtime_arn: str = "${AGENT_RUNTIME_ARN}"
) -> list[tuple[str, str, dict[str, Any]]]:
    """(service, operation, params) for the calls the run makes, for the service-model check
    (le_dispatch.api_shapes); the values are the first scenario's, the shape is every scenario's."""
    control, dp = "bedrock-agentcore-control", "bedrock-agentcore"
    session = runtime_session_id("eval", scenario["scenario_id"] if scenario else "C001")
    payload = json.dumps({"prompt": scenario["turns"][0]["input"]}) if scenario else '{"prompt": ""}'
    refs = reference_inputs(scenario, session) if scenario else []
    return [
        (
            control,
            "create_evaluator",
            {
                "evaluatorName": "LastElevatorOptionEquality",
                "level": "TRACE",
                "evaluatorConfig": {
                    "codeBased": {"lambdaConfig": {"lambdaArn": "${LAMBDA_ARN}", "lambdaTimeoutInSeconds": 60}}
                },
            },
        ),
        (
            dp,
            "invoke_agent_runtime",
            {"agentRuntimeArn": agent_runtime_arn, "runtimeSessionId": session, "payload": payload.encode()},
        ),
        (
            dp,
            "evaluate",
            {
                "evaluatorId": "Builtin.TrajectoryExactOrderMatch",
                "evaluationInput": {"sessionSpans": [SAMPLE_SPAN]},
                "evaluationReferenceInputs": refs,
            },
        ),
        (
            dp,
            "evaluate",
            {
                "evaluatorId": "${CUSTOM_EVALUATOR_ID}",
                "evaluationInput": {"sessionSpans": [SAMPLE_SPAN]},
                "evaluationReferenceInputs": refs,
            },
        ),
    ]


# one span in the shape the collector returns (the API takes the spans as documents; the check is about the
# call's members, the local evaluator tests cover what the spans carry)
SAMPLE_SPAN: dict[str, Any] = {
    "traceId": "0" * 32,
    "spanId": "0" * 16,
    "name": "execute_tool Plan",
    "attributes": {"gen_ai.tool.name": "Plan"},
    "events": [],
}


def scores_entry(scores: list[dict[str, Any]], *, model_id: str, mode: str, evaluator_id: str) -> dict[str, Any]:
    """Fold per-scenario AgentCore results (value 0..1 or label PASS/FAIL) into one results row."""
    passes = 0
    for r in scores:
        v = r.get("value")
        if v is None:
            v = 1.0 if str(r.get("label", "")).upper() == "PASS" else 0.0
        passes += 1 if float(v) >= 0.5 else 0
    cases = len(scores)
    return {
        "provider": PROVIDER,
        "model_id": model_id,
        "mode": mode,
        "evaluator": evaluator_id,
        "cases": cases,
        "agree": passes,
        "agreement_pct": round(100.0 * passes / cases, 1) if cases else None,
        "claimable": True,
        "note": "scores returned by AgentCore Evaluations",
    }


def write_scores(entry: dict[str, Any], path: Path = POLICY_AGREEMENT_PATH) -> dict[str, Any]:
    """Merge one agentcore-evaluations entry into results/policy_agreement.json.
    Existing entries are never overwritten; an entry with the same provider,
    model_id, mode and evaluator is replaced in place (idempotent reruns)."""
    doc = json.loads(path.read_text()) if path.exists() else {"entries": []}
    entries = doc.setdefault("entries", [])
    key = (entry["provider"], entry["model_id"], entry["mode"], entry.get("evaluator"))

    def _key(e: dict[str, Any]) -> tuple:
        return (e.get("provider"), e.get("model_id"), e.get("mode"), e.get("evaluator"))

    kept = [e for e in entries if _key(e) != key]
    kept.append(entry)
    doc["entries"] = kept
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def run_apply(p: EvalPlan, *, yes: bool = False) -> None:
    """Laptop only. Refuses without credentials and --yes; never exercised here."""
    if not credentials_present():
        raise RuntimeError("no AWS credentials in the environment; use --dry-run")
    if not yes:
        raise RuntimeError("refusing to run a live evaluation without --yes")
    raise NotImplementedError(
        "Run on the laptop with the starter toolkit's OnDemandEvaluationDatasetRunner over "
        "evals/agentcore/dataset.json, then fold results with scores_entry() and write_scores(); "
        "see docs/RUNBOOK-dispatch.md"
    )


def run_local_evaluation(
    cases: list[Case],
    kb: KBSet,
    policy: PolicyCallable,
    *,
    model_factory: Any,
    steering: bool = True,
) -> dict[str, Any]:
    """Run every scenario through the full stack with the in-memory OTel
    exporter, convert the real Strands spans to the evaluator payload shape,
    and run the custom evaluator on them. Proves the evaluator on real spans;
    the scores are plumbing proof for a scripted model, never a result."""
    from . import tracing
    from .evaluators.option_equality import evaluate
    from .gates import build_agent
    from .spans import evaluator_payload, session_spans

    exporter = tracing.memory_exporter()
    dataset = export_dataset(cases, kb, policy)
    per_scenario: list[dict[str, Any]] = []
    passes = 0
    where: Counter[str] = Counter()
    for i, (case, scenario) in enumerate(zip(cases, dataset["scenarios"], strict=False)):
        exporter.clear()
        trip = case_trip(case, i)
        bundle = build_agent(model_factory(case, trip), kb, policy, trip, steering=steering)
        try:
            bundle.agent(scenario["turns"][0]["input"])
        except Exception as exc:  # no plan delivered: the evaluator sees no option and fails the scenario
            tracing.add_span_event("local_eval.run_failed", scenario=scenario["scenario_id"], error=repr(exc))
        spans = session_spans(exporter)
        payload = evaluator_payload(spans, expected_option=scenario["metadata"]["expected_option"])
        result = evaluate(payload)
        ok = result.get("label") == "PASS"
        passes += int(ok)
        if ok:
            where[result["explanation"].split("(")[-1].split(")")[0]] += 1
        per_scenario.append({"scenario_id": scenario["scenario_id"], "spans": len(spans), **result})
    return {
        "provenance": {
            "run": f"scripted model over the {source_label()}, real Strands spans from the in-memory exporter",
            "claimable": False,
            "source": data_source(),
            "note": "Proves the custom evaluator parses real Strands OpenTelemetry spans. Scores for a scripted "
            "model are plumbing proof, never a result; the AgentCore run is the result.",
        },
        "scenarios": len(per_scenario),
        "pass": passes,
        "fail": len(per_scenario) - passes,
        "option_found_in": dict(where),
        "results": per_scenario,
    }


def write_local_results(doc: dict[str, Any], path: Path = LOCAL_RESULTS_PATH) -> None:
    write_results_json(path, doc)
