# Agents for Humans: deploying a scheduled background agent on Amazon Bedrock AgentCore

_Draft for builder.aws.com. This post is TODO until the deployment decision (C5) is made._

What is ready today, all offline and tested:

- One Strands agent with three tools, a `BeforeToolCall` hook, a steering handler with real
  Interrupts, and a structured Plan; a policy engine in pure Python; a poller that diffs the BART
  elevator feed every 5 minutes into SQLite; a FastAPI rider app with a decisions inbox.
- OpenTelemetry tracing to a file for the offline captures, with a one-line switch
  (`AGENTCORE_OBSERVABILITY=1`) to the OTLP exporter that AgentCore Observability reads.
- An MCP stdio server exposing the two grounding tools with the same guarantees.

What this post will cover once it happens (TODO):

- The AgentCore Runtime quota check (`make quota`) and the outcome.
- Packaging the agent for AgentCore Runtime, or the Lambda plus EventBridge fallback if the quota
  is zero.
- Scheduling the 5-minute poll and delivering messages.
- What it cost, from `results/`.
