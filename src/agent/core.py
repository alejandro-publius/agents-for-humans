"""Build the Last Elevator agent. One place decides which mechanisms are on.

``AgentConfig`` is also the ablation switch (A5): ``hooks_enabled=False, steering_enabled=False``
runs the same model and tools with every guardrail removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from agent.hooks import ArgumentValidatorHook, Validator, kb_elevator_validator, kb_station_validator
from agent.option_steering import OptionOrderSteering
from agent.schema import Plan
from agent.steering import SteeringHandler, option_order_policy, option_order_rewrite
from agent.tools import AGENT_TOOLS
from kb.load import known_abbrs

SYSTEM_PROMPT = """\
You are Last Elevator, a background agent for BART riders who depend on elevators.
You are given one elevator outage and one rider trip. Call get_station_facts for the station,
then plan_alternatives for the trip; it tells you whether the trip is affected, BART's documented
option, the ranked feasible options, and the minutes. Choose the first feasible option, call
draft_message with it, and finish by calling the Plan tool exactly once. Never name a station or
elevator that is not in the facts you were given, and never state minutes you did not receive.
"""


@dataclass
class AgentConfig:
    hooks_enabled: bool = True
    steering_enabled: bool = True
    structured_output: bool = True
    required_option: str | None = None
    known_stations: frozenset[str] = field(default_factory=known_abbrs)
    validators: dict[str, Validator] = field(default_factory=dict)
    system_prompt: str = SYSTEM_PROMPT

    @classmethod
    def ablated(cls, **overrides: Any) -> AgentConfig:
        return cls(hooks_enabled=False, steering_enabled=False, **overrides)


@dataclass
class BuiltAgent:
    agent: Agent
    config: AgentConfig
    validator_hook: ArgumentValidatorHook | None
    steering: SteeringHandler | None
    option_steering: OptionOrderSteering | None

    def __call__(self, prompt: str):
        return self.agent(prompt)


def default_validators(known: frozenset[str] | None = None) -> dict[str, Validator]:
    """Every station argument must be in the KB; every elevator argument must be listed for its station."""
    return {
        "get_station_facts": kb_station_validator("station_abbr"),
        "plan_alternatives": _both(
            kb_station_validator("origin", "destination", "outage_station"),
            kb_elevator_validator("outage_station", "outage_elevator"),
        ),
        "draft_message": kb_elevator_validator("station_abbr", "elevator"),
    }


def _both(*validators: Validator) -> Validator:
    def _run(args: dict[str, Any]) -> str | None:
        for v in validators:
            reason = v(args)
            if reason:
                return reason
        return None

    return _run


def build_agent(
    model: Any, *, config: AgentConfig | None = None, tools: list[Any] | None = None
) -> BuiltAgent:
    config = config or AgentConfig()
    validators = config.validators or default_validators(config.known_stations)

    hook = ArgumentValidatorHook(validators) if config.hooks_enabled else None
    steering = None
    option_steering = None
    if config.steering_enabled:
        steering = SteeringHandler(
            option_order_policy(config.required_option), option_order_rewrite(config.required_option)
        )
        option_steering = OptionOrderSteering(config.required_option)

    agent = Agent(
        name="last-elevator",
        model=model,
        tools=tools if tools is not None else AGENT_TOOLS,
        system_prompt=config.system_prompt,
        conversation_manager=SlidingWindowConversationManager(window_size=40),
        hooks=[hook] if hook else None,
        interventions=[steering] if steering else None,
        plugins=[option_steering] if option_steering else None,
        structured_output_model=Plan if config.structured_output else None,
        callback_handler=None,
    )
    return BuiltAgent(agent, config, hook, steering, option_steering)
