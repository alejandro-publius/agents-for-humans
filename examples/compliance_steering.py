"""Compliance steering for Strands Agents: enforce an external ranked policy, and never let the
model act on an entity that is not in your reference data.

Two mechanisms, both from the installed SDK (verified against strands-agents 1.55.x):

1. A ``SteeringHandler`` (``strands.vended_plugins.steering``) whose ``steer_before_tool`` returns
   ``Guide`` when the model's proposed choice is not the first feasible option of a ranked policy.
   The tool call is cancelled, the reason goes back to the model, and the model retries.
2. A ``HookProvider`` on ``BeforeToolCallEvent`` that sets ``event.cancel_tool`` when a tool
   argument names an entity outside a known set. The cancelled call returns an error result the
   model can see.

The policy and the entity set are plain Python here; in a real system they come from a document
your organisation publishes (a procedure, a price list, a catalogue). No network, no credentials:
the demo runs a scripted model so you can watch both mechanisms fire.

Run:  python compliance_steering.py
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable
from typing import Any

from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models.model import Model
from strands.vended_plugins.steering.core.action import Guide, Proceed
from strands.vended_plugins.steering.core.handler import SteeringHandler

# --- the external policy and reference data ----------------------------------------------------
# A ranked list of remedies for a broken thing, best first, from a published procedure.
POLICY_ORDER = ("repair_in_place", "swap_from_stock", "order_replacement", "escalate")
KNOWN_ASSETS = frozenset({"PUMP-1", "PUMP-2", "VALVE-7"})


def feasible_options(asset: str) -> list[str]:
    """What code says is feasible for this asset. The model chooses only among these."""
    stock = {"PUMP-1": False, "PUMP-2": True, "VALVE-7": True}
    options = [o for o in POLICY_ORDER if o != "swap_from_stock" or stock.get(asset)]
    return options


# --- tools ------------------------------------------------------------------------------------------
@tool
def asset_facts(asset_id: str) -> str:
    """Look up an asset. Args: asset_id: the asset identifier, for example PUMP-1."""
    return json.dumps({"asset_id": asset_id, "feasible_options": feasible_options(asset_id)})


@tool
def propose_action(asset_id: str, option: str, note: str) -> str:
    """Propose the remedy for an asset. Args: asset_id: the asset; option: one of the policy options;
    note: one sentence for the technician."""
    return json.dumps({"asset_id": asset_id, "option": option, "note": note})


# --- mechanism 1: compliance steering --------------------------------------------------------------
class ComplianceSteering(SteeringHandler):
    """Guide propose_action toward the first feasible option in POLICY_ORDER."""

    def __init__(self, required: dict[str, str]) -> None:
        super().__init__()
        self.required = required  # asset -> required option, computed by code
        self.guides: list[str] = []

    async def steer_before_tool(self, *, agent: Agent, tool_use: dict[str, Any], **kwargs: Any):
        if tool_use.get("name") != "propose_action":
            return Proceed(reason="not the action tool")
        args = tool_use.get("input") or {}
        want = self.required.get(args.get("asset_id"))
        if want and args.get("option") != want:
            self.guides.append(args.get("option"))
            return Guide(
                reason=f"Policy requires '{want}' first for {args['asset_id']}; propose that instead."
            )
        return Proceed(reason="compliant")


# --- mechanism 2: unknown-entity hook -------------------------------------------------------------
class KnownEntityHook(HookProvider):
    """Cancel any tool call whose asset_id is not in KNOWN_ASSETS."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)

    def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        asset = (event.tool_use.get("input") or {}).get("asset_id")
        if asset is not None and asset not in KNOWN_ASSETS:
            self.cancelled.append(asset)
            event.cancel_tool = f"CANCELLED: {asset!r} is not a known asset"


# --- a scripted model so the demo runs offline ------------------------------------------------------
class ScriptedModel(Model):
    """Plays back tool calls and text in order. Replace with BedrockModel() for a real run."""

    def __init__(self, turns: list[dict[str, Any]]) -> None:
        self.turns = list(turns)

    def update_config(self, **kw: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {"model_id": "scripted"}

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw) -> AsyncIterable[dict]:
        turn = self.turns.pop(0)
        usage = {
            "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": 1},
        }
        yield {"messageStart": {"role": "assistant"}}
        if turn["type"] == "tool_use":
            yield {
                "contentBlockStart": {"start": {"toolUse": {"toolUseId": turn["id"], "name": turn["name"]}}}
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn["input"])}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": turn["text"]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": usage}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kw):
        raise NotImplementedError
        yield


def main() -> int:
    # Code decides the required option per asset; the model only chooses among feasible ones.
    required = {a: feasible_options(a)[0] for a in KNOWN_ASSETS}
    hook = KnownEntityHook()
    steering = ComplianceSteering(required)
    model = ScriptedModel(
        [
            {
                "type": "tool_use",
                "id": "t1",
                "name": "asset_facts",
                "input": {"asset_id": "PUMP-9"},
            },  # unknown
            {"type": "tool_use", "id": "t2", "name": "asset_facts", "input": {"asset_id": "PUMP-1"}},
            {
                "type": "tool_use",
                "id": "t3",
                "name": "propose_action",
                "input": {"asset_id": "PUMP-1", "option": "escalate", "note": "Call the vendor."},
            },  # wrong
            {
                "type": "tool_use",
                "id": "t4",
                "name": "propose_action",
                "input": {
                    "asset_id": "PUMP-1",
                    "option": "repair_in_place",
                    "note": "Replace the seal on site.",
                },
            },
            {"type": "text", "text": "Proposed: repair PUMP-1 in place (replace the seal)."},
        ]
    )
    agent = Agent(
        model=model,
        tools=[asset_facts, propose_action],
        hooks=[hook],
        plugins=[steering],
        system_prompt="Look up the asset, then propose the first feasible remedy under the published policy.",
        callback_handler=None,
    )
    result = agent("PUMP-1 is leaking. What do we do?")

    print("hook cancelled unknown assets :", hook.cancelled)
    print("steering guided wrong options :", steering.guides)
    print("final answer                  :", str(result).strip())
    ok = hook.cancelled == ["PUMP-9"] and steering.guides == ["escalate"] and "repair" in str(result)
    print("demo", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
