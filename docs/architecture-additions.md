# Architecture diagram additions (keep the diagram honest)

The diagram in `docs/architecture.mmd` must show the user interface, the
Strands agent and its loop (model to tools to reasoning to response),
tools and integrations, AWS services, and output. F1, F2, F5 and F6 add
the nodes below. Policy and Evaluations shipped code in this package, so
they belong on the diagram, labelled "pending run" until the laptop runs
them.

```mermaid
flowchart LR
  subgraph Agent["Strands agent loop"]
    M[Model proposes] --> H[BeforeToolCallEvent hook: KB gate]
    H --> S1[Steering before tool: option order]
    S1 --> T[draft_plan tool: policy engine values]
    T --> M2[Model writes Plan]
    M2 --> S2[Steering after model: plan gate]
    S2 -->|Guide: discard and retry| M2
    S2 -->|Proceed| SO[Structured output: Plan]
    C[Per-run cap on model calls] -->|cap trips| CP[Code composes the plan]
  end
  CP --> R
  S1 -->|Interrupt after dark or last train| I[Decision card in the rider inbox]
  I -->|answer| SS[(Session state: decided cases)]
  SS --> S1
  SO --> R[Rider message: one of the code-composed sentences]
  subgraph AWS["AWS"]
    B[Amazon Bedrock model]
    RT[AgentCore Runtime]
    GW[AgentCore Gateway, MCP target]
    PE[AgentCore Policy engine: Cedar from the frozen KB, pending run]
    EV[AgentCore Evaluations: 194-case dataset, custom evaluator, pending run]
  end
  M --- B
  T --- GW
  GW --- PE
  SO -.-> EV
```

Trace events rendered in `docs/traces/`: hook.cancel_tool,
steering.guide, steering.guide_after_model, steering.proceed_after_model,
interrupt.raised, interrupt.resumed, delivery.composed_by_code.

Two nodes added after F17: the per-run cap on model calls (the SDK's
after-model retry loop is unbounded, so the cap is the only bound) and the
code-composed plan that reaches the rider when the cap trips. The rider
message node now says what it is: one of the sentences code composed from
the policy decision and BART's option text; the model only picks one.
