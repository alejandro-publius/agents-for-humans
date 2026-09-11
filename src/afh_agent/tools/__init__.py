"""Domain tools for the agent.

Every function decorated with @tool in this package is a capability the agent can call.
Keep tools small, deterministic, and unit-tested; the agent supplies the judgment.
"""

from afh_agent.tools.example import days_until

# Add new tools here so build_agent() picks them up.
DOMAIN_TOOLS = [days_until]

__all__ = ["DOMAIN_TOOLS", "days_until"]
