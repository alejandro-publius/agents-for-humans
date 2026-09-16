"""F5: AgentCore Policy scaffold. No AWS calls from the dispatch session.

`plan()` lists every resource `make agentcore-policy` would create and the
IAM permissions it needs. `--dry-run` prints the plan. `--apply` makes the
documented boto3 calls (client `bedrock-agentcore-control`) and runs only
when credentials exist and the operator passes `--yes`; it is never
exercised in tests.

Documented calls (AgentCore developer guide, policy-create-engine,
add-policies-to-engine, create-gateway-with-policy; boto3 reference,
create_gateway_target):

    create_policy_engine(name, description) -> policyEngineId, policyEngineArn
    create_policy(policyEngineId, name, validationMode="FAIL_ON_ANY_FINDINGS",
                  description, definition={"cedar": {"statement": <text>}}) -> policyId
    create_gateway(name, roleArn, protocolType="MCP", authorizerType, authorizerConfiguration,
                   policyEngineConfiguration={"mode": "ENFORCE", "arn": <engine arn>})
      or update_gateway(gatewayIdentifier, ..., policyEngineConfiguration=...)
    create_gateway_target(gatewayIdentifier, name, targetConfiguration={
        "mcp": {"mcpServer": {"endpoint": <E7 MCP server URL>}}},
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])

Region: us-west-2 (both Policy and Evaluations list it at launch; the
runbook says to confirm in the console before the first apply).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cedar_gen import POLICY_DIR, TOOLS_PATH, load_tools
from .interfaces import credentials_present as _credentials_present

DEFAULT_REGION = "us-west-2"

IAM_PERMISSIONS = [
    "bedrock-agentcore:CreatePolicyEngine",
    "bedrock-agentcore:GetPolicyEngine",
    "bedrock-agentcore:CreatePolicy",
    "bedrock-agentcore:GetPolicy",
    "bedrock-agentcore:ListPolicies",
    "bedrock-agentcore:CreateGateway",
    "bedrock-agentcore:UpdateGateway",
    "bedrock-agentcore:GetGateway",
    "bedrock-agentcore:CreateGatewayTarget",
    "bedrock-agentcore:GetGatewayTarget",
    "iam:PassRole (the gateway service role)",
    "bedrock-agentcore:InvokeGateway (the agent's runtime role, to call tools through the gateway)",
]


def credentials_present() -> bool:
    """One implementation for every apply path: see interfaces.credentials_present."""
    return _credentials_present()


@dataclass
class Step:
    order: int
    operation: str
    params: dict[str, Any]
    returns: str
    note: str = ""


@dataclass
class Plan:
    region: str
    steps: list[Step] = field(default_factory=list)
    iam: list[str] = field(default_factory=lambda: list(IAM_PERMISSIONS))

    def render(self) -> str:
        lines = [f"AgentCore Policy plan (region {self.region}); nothing below has been executed", ""]
        for s in self.steps:
            lines.append(f"{s.order}. {s.operation}")
            for k, v in s.params.items():
                if k == "definition":
                    statement = v["cedar"]["statement"]
                    count = statement.count("permit(") + statement.count("forbid(")
                    shown: Any = (
                        f'{{"cedar": {{"statement": "<{len(statement)} chars, {count} policies, '
                        f'infra/agentcore/policy/{s.params["name"]}.cedar>"}}}}'
                    )
                elif isinstance(v, str) and len(v) > 100:
                    shown = v[:100] + f"... ({len(v)} chars)"
                else:
                    shown = v
                lines.append(f"     {k}: {json.dumps(shown) if not isinstance(shown, str) else shown}")
            lines.append(f"     returns: {s.returns}")
            if s.note:
                lines.append(f"     note: {s.note}")
        lines.append("")
        lines.append("IAM permissions needed by the operator:")
        lines.extend(f"  - {p}" for p in self.iam)
        return "\n".join(lines)


def plan(
    *,
    policy_dir: Path = POLICY_DIR,
    tools_path: Path = TOOLS_PATH,
    region: str = DEFAULT_REGION,
    engine_name: str = "last-elevator-policy-engine",
    gateway_name: str = "last-elevator-gateway",
    gateway_id: str | None = None,
    gateway_role_arn: str = "${GATEWAY_ROLE_ARN}",
    mcp_endpoint: str | None = None,
) -> Plan:
    manifest = json.loads((policy_dir / "manifest.json").read_text())
    target, _tools = load_tools(tools_path)
    tools_doc = json.loads(Path(tools_path).read_text())
    endpoint = mcp_endpoint or tools_doc.get("mcp_endpoint", "${MCP_ENDPOINT}")
    p = Plan(region=region)
    n = 1
    p.steps.append(
        Step(
            n,
            "bedrock-agentcore-control.create_policy_engine",
            {"name": engine_name, "description": f"Last Elevator KB gate, {manifest['kb_frozen_tag']}"},
            "policyEngineId, policyEngineArn",
        )
    )
    for fname in manifest["files"]:
        n += 1
        text = (policy_dir / fname).read_text()
        p.steps.append(
            Step(
                n,
                "bedrock-agentcore-control.create_policy",
                {
                    "policyEngineId": "<from step 1>",
                    "name": fname.removesuffix(".cedar"),
                    "validationMode": manifest["validation_mode"],
                    "description": f"generated from {manifest['kb_frozen_tag']}",
                    "definition": {"cedar": {"statement": text.replace("${GATEWAY_ARN}", "<gateway arn>")}},
                },
                "policyId",
                note="the ${GATEWAY_ARN} placeholder is substituted with the gateway's ARN before the call",
            )
        )
    n += 1
    if gateway_id:
        p.steps.append(
            Step(
                n,
                "bedrock-agentcore-control.get_gateway",
                {"gatewayIdentifier": gateway_id},
                "name, roleArn, authorizerType, protocolType, authorizerConfiguration, gatewayArn",
                note="update_gateway requires the gateway's name, roleArn and authorizerType again; read them first",
            )
        )
        n += 1
        p.steps.append(
            Step(
                n,
                "bedrock-agentcore-control.update_gateway",
                {
                    "gatewayIdentifier": gateway_id,
                    "name": "<from get_gateway>",
                    "roleArn": "<roleArn from get_gateway>",
                    "authorizerType": "<from get_gateway>",
                    "policyEngineConfiguration": {"mode": "ENFORCE", "arn": "<policyEngineArn from step 1>"},
                },
                "gatewayArn, status",
                note="existing gateway: attach the engine in ENFORCE mode; protocolType, authorizerConfiguration "
                "and description are passed through from get_gateway when present",
            )
        )
    else:
        p.steps.append(
            Step(
                n,
                "bedrock-agentcore-control.create_gateway",
                {
                    "name": gateway_name,
                    "roleArn": gateway_role_arn,
                    "protocolType": "MCP",
                    "authorizerType": "AWS_IAM",
                    "policyEngineConfiguration": {"mode": "ENFORCE", "arn": "<policyEngineArn from step 1>"},
                },
                "gatewayId, gatewayArn, gatewayUrl",
                note="policies reference the gateway ARN; create the gateway first, then create the policies with "
                "the real ARN (the apply path orders it that way)",
            )
        )
    n += 1
    p.steps.append(
        Step(
            n,
            "bedrock-agentcore-control.create_gateway_target",
            {
                "gatewayIdentifier": "<gatewayId>",
                "name": target,
                "targetConfiguration": {"mcp": {"mcpServer": {"endpoint": endpoint}}},
                "credentialProviderConfigurations": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
            },
            "targetId, status",
            note="the E7 MCP server (FastMCP, two-hour cap) is the target; tools appear as "
            f"{target}___<tool>. If the docs require a Lambda wrapper for this server, swap the "
            "targetConfiguration to mcp.lambda with an inline toolSchema built from tools.json",
        )
    )
    return p


UPDATE_GATEWAY_PASSTHROUGH = (
    "name",
    "roleArn",
    "authorizerType",
    "authorizerConfiguration",
    "protocolType",
    "protocolConfiguration",
    "description",
    "exceptionLevel",
    "kmsKeyArn",
    "interceptorConfigurations",
)


def update_gateway_params(
    gateway_id: str, existing: dict[str, Any], policy_engine_configuration: dict[str, Any]
) -> dict[str, Any]:
    """update_gateway is a full update: the service requires name, roleArn and authorizerType again and would
    drop what is left out, so every setting get_gateway returned is passed through, plus the engine."""
    params: dict[str, Any] = {"gatewayIdentifier": gateway_id}
    for key in UPDATE_GATEWAY_PASSTHROUGH:
        if existing.get(key) not in (None, "", [], {}):
            params[key] = existing[key]
    params["policyEngineConfiguration"] = policy_engine_configuration
    return params


def api_calls(p: Plan) -> list[tuple[str, str, dict[str, Any]]]:
    """(service, operation, params) for every step, for the service-model check (le_dispatch.api_shapes)."""
    out = []
    for s in p.steps:
        service, operation = s.operation.split(".", 1)
        out.append((service, operation, s.params))
    return out


def apply(p: Plan, *, yes: bool = False, region: str = DEFAULT_REGION) -> dict[str, Any]:
    """Make the calls. Refuses without credentials and without --yes. Not
    exercised by tests or by the dispatch session."""
    if not credentials_present():
        raise RuntimeError("no AWS credentials in the environment; use --dry-run")
    if not yes:
        raise RuntimeError("refusing to create resources without --yes")
    import boto3  # imported here so the package never needs boto3 for dry runs

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    created: dict[str, Any] = {}
    engine = client.create_policy_engine(**p.steps[0].params)
    created["policyEngineArn"] = engine["policyEngineArn"]
    created["policyEngineId"] = engine["policyEngineId"]
    gw_step = next(s for s in p.steps if s.operation.endswith(("create_gateway", "update_gateway")))
    gw_params = {**gw_step.params, "policyEngineConfiguration": {"mode": "ENFORCE", "arn": created["policyEngineArn"]}}
    if gw_step.operation.endswith("update_gateway"):
        existing = client.get_gateway(gatewayIdentifier=gw_params["gatewayIdentifier"])
        gw_params = update_gateway_params(
            gw_params["gatewayIdentifier"], existing, gw_params["policyEngineConfiguration"]
        )
        gw = client.update_gateway(**gw_params)
    else:
        gw = client.create_gateway(**gw_params)
    created["gatewayArn"] = gw["gatewayArn"]
    created["gatewayId"] = gw.get("gatewayId", gw_params.get("gatewayIdentifier"))
    created["policyIds"] = []
    for s in p.steps:
        if s.operation.endswith("create_policy"):
            params = dict(s.params)
            params["policyEngineId"] = created["policyEngineId"]
            statement = s.params["definition"]["cedar"]["statement"].replace("<gateway arn>", created["gatewayArn"])
            params["definition"] = {"cedar": {"statement": statement}}
            created["policyIds"].append(client.create_policy(**params)["policyId"])
    tgt_step = next(s for s in p.steps if s.operation.endswith("create_gateway_target"))
    tgt = client.create_gateway_target(**{**tgt_step.params, "gatewayIdentifier": created["gatewayId"]})
    created["targetId"] = tgt["targetId"]
    return created
