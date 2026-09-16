"""make evaluator-zip: the custom evaluator as a Lambda deployment package, verified before it is uploaded.

Writes build/evaluator/option_equality.zip (the one module, no dependencies, handler
`option_equality.lambda_handler`), then imports the module from the zip alone in an isolated interpreter (no
le_dispatch on the path) and runs the handler on real Strands spans from a scripted run, with the reference
input in the Evaluate API's shape. Prints the create-function and create-evaluator steps. Nothing is called.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch import tracing  # noqa: E402
from le_dispatch.gates import build_agent, deliver  # noqa: E402
from le_dispatch.interfaces import Trip, fixture_policy  # noqa: E402
from le_dispatch.messages import composed_plan  # noqa: E402
from le_dispatch.scripted_model import ScriptedModel, plan_call, tool_call  # noqa: E402
from le_dispatch.spans import evaluator_payload, session_spans  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "le_dispatch" / "evaluators" / "option_equality.py"
OUT = ROOT / "build" / "evaluator" / "option_equality.zip"

PROBE = r"""
import json, sys
zip_path, payload_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, zip_path)
import option_equality
assert option_equality.__file__.startswith(zip_path), option_equality.__file__
payload = json.load(open(payload_path))
verdict = option_equality.lambda_handler(payload, None)
print(json.dumps(verdict))
"""


def build_zip(out: Path = OUT) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("option_equality.py", date_time=(2026, 1, 1, 0, 0, 0))  # a stable archive
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, MODULE.read_bytes())
    return out


def real_payload() -> dict:
    """Real Strands spans from one compliant scripted run, with the API-shaped reference input."""
    kb, policy = fixture_policy()
    trip = Trip("rider-zip", "DELN", "EMBR", ("DELN-E1",))
    d = policy(trip)
    exporter = tracing.memory_exporter()
    exporter.clear()
    model = ScriptedModel(
        [
            tool_call("draft_plan", {"station": d.station, "elevator": d.elevator, "option": d.top_option}, "t1"),
            plan_call(composed_plan(d), "p1"),
        ]
    )
    out = deliver(build_agent(model, kb, policy, trip))
    assert out.composed_by == "model"
    return evaluator_payload(session_spans(exporter), expected_option=d.top_option)


def verify(zip_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="le-evaluator-") as tmp:
        payload_path = Path(tmp) / "payload.json"
        payload_path.write_text(json.dumps(real_payload()))
        run = subprocess.run(
            [sys.executable, "-I", "-c", PROBE, str(zip_path), str(payload_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    if run.returncode != 0:
        raise SystemExit(f"the zipped evaluator failed in an isolated interpreter:\n{run.stdout}{run.stderr}")
    return json.loads(run.stdout.strip().splitlines()[-1])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--function-name", default="last-elevator-option-equality")
    args = ap.parse_args(argv)
    zip_path = build_zip(Path(args.out))
    verdict = verify(zip_path)
    if verdict.get("label") != "PASS":
        print(f"the zipped evaluator returned {verdict}")
        return 1
    size = zip_path.stat().st_size
    print(f"wrote {zip_path.relative_to(ROOT) if zip_path.is_relative_to(ROOT) else zip_path} ({size} bytes)")
    print(f"verified: imported from the zip alone in an isolated interpreter, real spans: {verdict}")
    print("\nlaptop steps (nothing below has been executed):")
    print(
        f"1. aws lambda create-function --function-name {args.function_name} --runtime python3.11 "
        f"--handler option_equality.lambda_handler --zip-file fileb://{zip_path} --role <lambda execution role arn> "
        "--timeout 60 --region us-west-2"
    )
    print(
        "2. create_evaluator(evaluatorName='LastElevatorOptionEquality', level='TRACE', evaluatorConfig="
        "{'codeBased': {'lambdaConfig': {'lambdaArn': <function arn>, 'lambdaTimeoutInSeconds': 60}}}); the "
        "evaluations execution role needs lambda:InvokeFunction and lambda:GetFunction on it; put the ARN in "
        "evals/agentcore/evaluators.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
