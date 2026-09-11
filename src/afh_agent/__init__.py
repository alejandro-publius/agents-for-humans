"""Agents for Humans hackathon entry, built on the Strands Agents SDK.

Public surface:
    build_agent()  -> a configured strands.Agent
    build_model()  -> the model provider selected by environment variables
"""

from afh_agent.agent import build_agent
from afh_agent.models import build_model

__all__ = ["build_agent", "build_model"]
