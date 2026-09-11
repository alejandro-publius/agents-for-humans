"""Build the Last Elevator agent. One place decides which mechanisms are on.

``AgentConfig`` is also the ablation switch (A5): ``hooks_enabled=False, steering_enabled=False``
runs the same model and tools with the guardrails removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from agent.hooks import ArgumentValidatorHook, Validator, station_code_validator
from agent.schema import Plan
from agent.steering import SteeringHandler, option_order_policy, option_order_rewrite
from agent.tools import PLACEHOLDER_STATIONS, PLACEHOLDER_TOOLS

SYSTEM_PROMPT = """\
You are Last Elevator, a background agent for BART riders who depend on elevators.
You are given one elevator outage and one rider trip. Use the tools to look up station facts and
feasible options. Code decides feasibility and minutes; you choose among feasible options, in BART's
published order, and write the rider's message. Finish by calling the Plan tool exactly once.
"""


@dataclass
class AgentConfig:
    hooks_enabled: bool = True
    steering_enabled: bool = True
    structured_output: bool = True
    required_option: str | None = None
    known_stations: frozenset[str] = PLACEHOLDER_STATIONS
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

    def __call__(self, prompt: str):
        return self.agent(prompt)


def default_validators(known: frozenset[str]) -> dict[str, Validator]:
    return {
        "get_station_facts": station_code_validator(known, "station"),
        "plan_alternatives": station_code_validator(known, "origin", "destination"),
    }


def build_agent(
    model: Any, *, config: AgentConfig | None = None, tools: list[Any] | None = None
) -> BuiltAgent:
    config = config or AgentConfig()
    validators = config.validators or default_validators(config.known_stations)

    hook = ArgumentValidatorHook(validators) if config.hooks_enabled else None
    steering = None
    if config.steering_enabled:
        steering = SteeringHandler(
            option_order_policy(config.required_option), option_order_rewrite(config.required_option)
        )

    agent = Agent(
        name="last-elevator",
        model=model,
        tools=tools if tools is not None else PLACEHOLDER_TOOLS,
        system_prompt=config.system_prompt,
        conversation_manager=SlidingWindowConversationManager(window_size=40),
        hooks=[hook] if hook else None,
        interventions=[steering] if steering else None,
        structured_output_model=Plan if config.structured_output else None,
        callback_handler=None,
    )
    return BuiltAgent(agent=agent, config=config, validator_hook=hook, steering=steering)
