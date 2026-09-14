"""Every AWS call the apply paths make, checked against the AWS service model, offline.

botocore ships the service models (parameter names, required members, enums, lengths) for
`bedrock-agentcore-control` and `bedrock-agentcore`; `botocore.validate` is what rejects a bad call before it
leaves the laptop. Running the same validation here, over the dry-run plans, means a misnamed or missing
parameter fails `make verify` today instead of the first `--apply` on Sunday. Placeholders in the plans
(`<from step 1>`, `${GATEWAY_ROLE_ARN}`) are replaced with values of the right shape before validating; the
check is about the calls' shape, never about the values.
"""

from __future__ import annotations

import functools
import re
from typing import Any

PLACEHOLDER = re.compile(r"^(<.*>|\$\{.*\})$")
SAMPLE_ACCOUNT = "123456789012"


def _operation_name(python_name: str) -> str:
    return "".join(part.capitalize() for part in python_name.split("_"))


def sample_value(key: str, placeholder: str) -> str:
    """A stand-in of the right shape for a placeholder: an ARN for *Arn keys or ARN placeholders, a URL for
    endpoints, an id long enough for the id shapes otherwise."""
    low = (key + " " + placeholder).lower()
    if "endpoint" in low or "url" in low:
        return "https://example.com/mcp"
    if "arn" in low:
        if "role" in low:
            return f"arn:aws:iam::{SAMPLE_ACCOUNT}:role/sample-role"
        return f"arn:aws:bedrock-agentcore:us-west-2:{SAMPLE_ACCOUNT}:gateway/sample-gateway-id"
    return "sampleid0123456789"


def fill_placeholders(params: Any, key: str = "") -> Any:
    if isinstance(params, dict):
        return {k: fill_placeholders(v, k) for k, v in params.items()}
    if isinstance(params, list):
        return [fill_placeholders(v, key) for v in params]
    if isinstance(params, str) and PLACEHOLDER.match(params):
        return sample_value(key, params)
    return params


@functools.cache
def _service_model(service: str) -> Any:
    """The service model, loaded once per process (botocore reads and parses the JSON on every lookup
    otherwise, about a tenth of a second each; the stand-ins validate every call)."""
    import botocore.session

    return botocore.session.get_session().get_service_model(service)


def validate_call(service: str, operation: str, params: dict[str, Any]) -> str | None:
    """None when the call's shape is valid, else botocore's message."""
    from botocore.exceptions import ParamValidationError
    from botocore.validate import validate_parameters

    model = _service_model(service)
    name = operation if operation[:1].isupper() else _operation_name(operation)
    if name not in model.operation_names:
        return f"{service} has no operation {name}"
    try:
        validate_parameters(fill_placeholders(params), model.operation_model(name).input_shape)
    except ParamValidationError as exc:
        return str(exc).replace("\n", " ")
    return None


def check_calls(calls: list[tuple[str, str, dict[str, Any]]]) -> list[str]:
    """Problems as `service.operation: message`; empty when every call is well formed."""
    problems = []
    for service, operation, params in calls:
        message = validate_call(service, operation, params)
        if message:
            problems.append(f"{service}.{operation}: {message}")
    return problems


@functools.cache
def service_models_available() -> bool:
    try:
        _service_model("bedrock-agentcore-control")
        _service_model("bedrock-agentcore")
    except Exception:  # an old botocore without the AgentCore models, or none at all
        return False
    return True
