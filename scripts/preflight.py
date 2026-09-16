"""make preflight: is this machine ready for the laptop-only runs? Calls nothing.

Checks, each printed as ok / warn / FAIL with what to do:
- Python 3.11 or newer; strands-agents 1.55.1 (the version the gates were built and measured against)
- optional packages: cedarpy (local Cedar evaluation), bedrock-agentcore (the runtime app), boto3
- the data: LE_KB_EXPORT and LE_CASES_EXPORT set and parseable, or the fixtures (a warning)
- credentials in the environment (never read from files, never used here) and a region
- the generated files are current (the transcript regenerates byte-identical)
Exit 1 on any FAIL. Warnings do not fail.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch import live  # noqa: E402
from le_dispatch.agentcore_eval import export_dataset  # noqa: E402
from le_dispatch.agentcore_eval import plan as eval_plan  # noqa: E402
from le_dispatch.agentcore_memory import memory_plan  # noqa: E402
from le_dispatch.agentcore_policy import api_calls as policy_api_calls  # noqa: E402
from le_dispatch.agentcore_policy import plan as policy_plan  # noqa: E402
from le_dispatch.api_shapes import check_calls, service_models_available  # noqa: E402
from le_dispatch.eval_live import credentials_present, load_models  # noqa: E402
from le_dispatch.interfaces import (  # noqa: E402
    CASES_EXPORT_ENV,
    KB_EXPORT_ENV,
    ROOT,
    FixturePolicy,
    cases_path,
    claimable,
    kb_path,
    load_cases,
    load_kb,
)

PINNED_STRANDS = "1.55.1"


def check(rows: list[tuple[str, str, str]], status: str, what: str, detail: str = "") -> None:
    rows.append((status, what, detail))


def fixture_stack_for_plan() -> tuple:
    """The KB and policy the evaluation plan is built from (the exports when set, else the fixtures)."""
    kb = load_kb()
    return kb, FixturePolicy(load_cases(), kb)


def run(argv: list[str] | None = None, *, regenerate: bool = True) -> tuple[list[tuple[str, str, str]], int]:
    rows: list[tuple[str, str, str]] = []
    v = sys.version_info
    check(
        rows,
        "ok" if v >= (3, 11) else "FAIL",
        f"python {v.major}.{v.minor}.{v.micro}",
        "" if v >= (3, 11) else "need 3.11+",
    )
    try:
        strands_version = importlib.metadata.version("strands-agents")
        check(
            rows,
            "ok" if strands_version == PINNED_STRANDS else "warn",
            f"strands-agents {strands_version}",
            ""
            if strands_version == PINNED_STRANDS
            else f"measured against {PINNED_STRANDS}; run pytest tests/test_upstream_note.py first",
        )
    except importlib.metadata.PackageNotFoundError:
        check(rows, "FAIL", "strands-agents not installed", "pip install -e .")
    for module, why in (
        ("cedarpy", "local Cedar evaluation tests"),
        ("bedrock_agentcore", "the runtime app"),
        ("boto3", "the apply paths"),
    ):
        try:
            importlib.import_module(module)
            check(rows, "ok", f"{module} importable")
        except ImportError:
            check(rows, "warn", f"{module} not installed", f"{why} skip; pip install -e '.[dev,cedar,aws]'")
    kb_set, cases_set = os.environ.get(KB_EXPORT_ENV), os.environ.get(CASES_EXPORT_ENV)
    if kb_set and cases_set:
        try:
            kb = load_kb()
            cases = load_cases()
            check(
                rows,
                "ok",
                f"exports: {len(kb.stations)} stations, {len(kb.elevators)} elevators, {len(cases)} cases, "
                f"tag {kb.frozen_tag or '?'}",
                f"{kb_path()} and {cases_path()}; results will be claimable={claimable()}",
            )
        except (OSError, ValueError, KeyError) as exc:
            check(rows, "FAIL", "exports set but unreadable", repr(exc))
    elif kb_set or cases_set:
        check(rows, "FAIL", "only one of the two exports is set", f"set both {KB_EXPORT_ENV} and {CASES_EXPORT_ENV}")
    else:
        check(
            rows,
            "warn",
            "fixtures in use (exports not set)",
            f"set {KB_EXPORT_ENV} and {CASES_EXPORT_ENV} before the real runs",
        )
    cfg = load_models()
    region = cfg.get("region", "")
    creds = credentials_present()
    check(
        rows,
        "ok" if creds else "warn",
        "AWS credentials found (environment or the shared credentials file)"
        if creds
        else "no AWS credentials in the environment or the shared credentials file",
        f"region {region}; models {', '.join(m.model_id for m in cfg['models'])}"
        if creds
        else "live targets will stay dry runs",
    )
    if region:
        check(rows, "ok", f"region {region} configured in evals/live_models.json")
    probe = live.model(
        cfg["models"][0].model_id if cfg.get("models") else "us.amazon.nova-lite-v1:0", region or "us-west-2"
    )
    configured = live.client_is_live_configured(probe.client)
    w = live.worst_case()
    check(
        rows,
        "ok" if configured else "FAIL",
        "one retry layer on the live path: botocore's off, Strands' bounded"
        if configured
        else "the live client is not on the live configuration",
        f"a throttled model call costs at most {w['throttled_requests']} requests and {w['throttled_seconds']} s "
        f"(waits {', '.join(str(s) for s in w['waits_seconds'])}); a hung stream {w['hung_seconds']} s, "
        "then code composes",
    )
    if service_models_available():
        calls = (
            policy_api_calls(policy_plan())
            + eval_plan(export_dataset(load_cases(), *fixture_stack_for_plan())).api_calls
            + memory_plan()["calls"]
        )
        problems = check_calls(calls)
        check(
            rows,
            "ok" if not problems else "FAIL",
            f"every planned AWS call is well formed ({len(calls)} call shapes against botocore's service models)"
            if not problems
            else f"{len(problems)} planned AWS call(s) botocore would reject",
            "; ".join(problems)[:300],
        )
    else:
        check(
            rows, "warn", "botocore without the AgentCore service models", "pip install -e '.[aws]' to check the calls"
        )
    transcript = ROOT / "docs" / "TOUR-TRANSCRIPT.md"
    if regenerate and transcript.exists():
        before = transcript.read_bytes()
        try:
            subprocess.run(
                ["make", "--no-print-directory", "transcript"], cwd=ROOT, check=True, capture_output=True, timeout=600
            )
            same = transcript.read_bytes() == before
            check(
                rows,
                "ok" if same else "FAIL",
                "transcript regenerates byte-identical" if same else "transcript changed on regeneration",
                "" if same else "commit the regenerated docs/TOUR-TRANSCRIPT.md, or the code moved",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            check(rows, "warn", "could not regenerate the transcript", repr(exc)[:120])
    failures = sum(1 for s, _, _ in rows if s == "FAIL")
    return rows, 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    quick = "--quick" in (argv if argv is not None else sys.argv[1:])  # skip the transcript regeneration (25 s)
    rows, code = run(argv, regenerate=not quick)
    for status, what, detail in rows:
        print(f"{status:5} {what}" + (f"  ({detail})" if detail else ""))
    print("preflight: " + ("FAILED" if code else "ok") + f" ({sum(1 for s, _, _ in rows if s == 'warn')} warning(s))")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
