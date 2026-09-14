# Architecture of the dispatch package

Two diagrams, both rendered by GitHub. The first is one poll for one
rider: where code decides, where the model proposes, where each gate
sits, and what reaches the rider; the rider's note enters outside the
trusted inputs, as text, and becomes a constraint only through the fixed
vocabulary and the quote check. The second is the human moment across
processes: the poller pauses, the app answers, a later poll resumes.
AgentCore Policy, Evaluations and Memory are shown where they attach and
are labelled pending until the laptop runs them.

## One poll, one rider

```mermaid
flowchart TB
  subgraph Inputs["Inputs (trusted for facts)"]
    F[BART elevator feed<br/>polled every 5 min] --> O[Outages now]
    KB[(Frozen KB<br/>kb-labels-v1: 50 stations,<br/>97 elevators, 194 options)]
    T[Rider's saved trip]
  end
  N[Rider's note, their own words<br/>no ramps today: text, not a fact]
  O --> PE
  T --> PE
  KB --> PE
  N --> RN[RiderNote, structured output<br/>the model may only return<br/>a fixed vocabulary plus the quote]
  RN -->|code checks each quote<br/>is in the note| FE[Constraints as feasibility only<br/>an option ruled out, BART's order<br/>and minutes stand]
  FE --> PE
  PE{Policy engine<br/>pure code: affected?<br/>BART's order, minutes}
  PE -->|not affected| Q[Quiet: nothing sent,<br/>open question withdrawn<br/>if the elevator is back]
  PE -->|affected| A
  subgraph A["Strands agent (models propose, code decides)"]
    direction TB
    M[Model proposes<br/>Bedrock: Sonnet or Nova Lite] --> H
    H[KB hook<br/>BeforeToolCallEvent:<br/>cancel a foreign station<br/>or elevator] --> S1
    S1[Option gate<br/>steer_before_tool:<br/>Guide to BART's top option] --> I
    I{After dark or<br/>last train?}
    I -->|yes| INT[Interrupt: pause,<br/>decision card to the inbox]
    INT -.->|rider says yes:<br/>resumed later| TL
    INT -.->|rider says no| HOLD[Plan held on file,<br/>nothing sent]
    I -->|no| TL[draft_plan tool<br/>returns the policy engine's values<br/>and the approved sentences]
    TL --> M2[Model writes the Plan<br/>structured output]
    M2 --> S2[Plan gate<br/>steer_after_model:<br/>station, elevator, option,<br/>minutes, prose, approved sentence]
    S2 -->|Guide: discard, retry| M2
    S2 -->|Proceed| P[Plan]
    C[Per-run cap on model calls] -.->|cap trips| CP[Code composes the plan]
  end
  P --> R[Rider: one of the<br/>code-composed sentences]
  CP --> R
  R --> EV[Evidence packet:<br/>what code decided, what the<br/>model tried, what stopped it,<br/>what reached the rider, what it cost]
  subgraph AWS["AWS"]
    B[Amazon Bedrock]
    RT[AgentCore Runtime<br/>the same build_agent behind<br/>/invocations]
    GW[AgentCore Gateway<br/>MCP target]
    POL[AgentCore Policy<br/>Cedar generated from the KB<br/>pending run]
    EVAL[AgentCore Evaluations<br/>194-case dataset, custom<br/>option-equality evaluator<br/>pending run]
    MEM[AgentCore Memory<br/>the rider's decisions,<br/>one event per answer,<br/>best effort: an outage<br/>never fails a delivery<br/>pending run]
  end
  M --- B
  TL -.->|the same tool contract,<br/>served through the gateway<br/>by the main repo's MCP server| GW
  GW --- POL
  EV -.-> EVAL
  INT -.->|the answer, written through;<br/>read back in a later session| MEM
  A --- RT
```

What the shapes mean: the diamond decisions are code and never a model;
the model appears twice (proposing a tool call, writing the Plan) and is
gated both times; the dotted cap is the bound the SDK does not provide
(`docs/UPSTREAM-NOTE.md`); the Cedar policy at the gateway is the
in-process hook's twin, enforcing the same rule outside the process for
the tool when the main repo's MCP server serves it through the gateway
(in this package the tool runs in-process, behind the hook).

## The human moment across processes

```mermaid
sequenceDiagram
  autonumber
  participant Poll1 as Poller (poll n)
  participant Agent as Strands agent
  participant Inbox as Inbox (JSON, locked)
  participant App as Rider app
  participant Poll2 as Poller (poll n+1)
  Poll1->>Agent: run(trip, after dark)
  Agent->>Agent: KB hook, option gate pass
  Agent-->>Inbox: decision card (plain words,<br/>BART's option, minutes, source, rejected)
  Agent-->>Poll1: stop_reason = interrupt, interrupt ids
  Poll1->>Inbox: store interrupt ids on the card
  Note over Poll1,Poll2: The session manager persists the paused run<br/>(messages, agent.state, the pending interrupt)
  App->>Inbox: rider answers yes (or no)
  Poll2->>Inbox: read the card and its interrupt ids
  Poll2->>Agent: resume with interruptResponse
  Agent->>Agent: answer stored in agent.state (never asked twice)
  Agent->>Agent: plan gate: status send (yes) or hold (no)
  Agent-->>Poll2: Plan
  Poll2-->>App: sent, or held on file
  Note over Inbox,Poll2: Elevator back before the answer?<br/>The card is withdrawn, nothing is sent,<br/>a late answer is refused
  Note over Inbox,Poll2: Still out in the morning, no answer?<br/>The question is superseded (daytime asks nothing)<br/>and the plan is sent. A late answer gets already_sent
```

The sequence is the one `test_pause_and_resume_across_processes_with_file_session_manager`
runs in three processes with a `FileSessionManager`, and the runtime
entrypoint (`infra/agentcore/runtime/entrypoint.py`) exposes as the
`pending`, `sent`, `held`, `withdrawn` and `already_sent` states; an
answer never returns an error (a double tap, a changed mind and an
answer to a question this container never asked each get a plain state
back).
