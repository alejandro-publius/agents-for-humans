# Agents for Humans: the evidence packet, what a rider and a judge can read after the agent decides

An agent that works in the background has to be auditable after the fact.
For Last Elevator, a BART elevator-outage agent built with the Strands
Agents SDK, the evidence packet for one decision is three things: the
decision card, the trace of which gate fired, and the results files that
CI checks.

## The decision card

After dark, or at the last train, the agent does not send a reroute on its
own. A steering handler returns `Interrupt`; Strands pauses the run
(`stop_reason == "interrupt"`) and the rider's inbox gets a card:

```json
{
  "station": "DELN",
  "elevator": "DELN-E1",
  "option": "alternate_elevator",
  "added_minutes": 4,
  "flags": {"after_dark": true, "last_train": false},
  "source_url": "https://www.bart.gov/stations/deln/accessible",
  "rejected": [{"label": "transit", "reason": "Take AC Transit or Muni from DELN to the next accessible station"}],
  "question": "It is after dark. DELN elevator DELN-E1 is out at your starting station. BART's option is the alternate elevator route at the same station, about 4 minutes more. Send this plan now?"
}
```

Every field is code's output: the option and minutes come from the policy
engine, the source URL from BART's station page in the frozen knowledge
base, the rejected options from the policy engine's ranking, and the
sentence the rider reads is one of a few that code composed from the
decision and BART's own wording; the model only picked it. When the model
never picks one, code sends the first, and the packet says so. The packet
also says what the decision cost, in model calls and tokens from Strands'
own metrics, and draws every model action on its sequence diagram: the
calls a gate stopped and the one it let through. The rider
answers; the run resumes with
`agent([{"interruptResponse": {"interruptId": ..., "response": true}}])`;
the answer is stored in `agent.state`, which Strands session managers
persist, so the same case never asks twice. A rider's note gets its own
packet too: the words, what the model read them as, and the one option
that went out of reach because of them, with BART's next option and the
policy engine's minutes in its place.

## The trace

Strands already emits OpenTelemetry spans, and a cancelled tool call shows
up as an error span with the cancel text. Last Elevator adds named events
on top so a reader sees which gate fired:

```
hook.cancel_tool               span=execute_tool draft_plan reason="Cancelled: elevator='FAKE-E7' is not an elevator in the knowledge base"
steering.guide                 span=execute_tool draft_plan reason="BART's published order puts 'alternate_elevator' first"
steering.guide_after_model     span=execute_event_loop_cycle plan.option='transit' reason="Plan rejected: option 'transit' is not the policy engine's top feasible option"
steering.proceed_after_model   span=execute_event_loop_cycle plan.option='alternate_elevator' plan.added_minutes=4
interrupt.raised               span=execute_tool draft_plan case_key='rider|DELN>EMBR|DELN-E1'
```

A judge who reads that trace knows the model tried a fake elevator, a
wrong option, and a wrong final plan, and that none of it reached the
rider.

## The results files

Every number in the README comes from a file under `results/` and a
claims table that `make verify` checks: red-team counts, the quiet metric,
the policy-agreement rows per model and mode, the dataset statistics.
Files from fixture runs carry `provenance.claimable: false` and the docs
say "pending" next to them; nothing is a result until the real run exists.
Once a real run exists, a fixture run can never overwrite its file: every
results writer checks the file's own provenance first, so a target typed
without the exports, or CI, which has neither the exports nor the archive,
leaves the real numbers alone and says so.
The two-model table, once its live rows land, makes the case for
architecture over model choice: the gates carry the guarantee, and
swapping the model changes the cost, not the promise.

## AgentCore, the same idea one layer down

The knowledge-base rule also compiles to Cedar for Amazon Bedrock
AgentCore Policy: a governed tool may be called only with stations and
elevators in the frozen set and option labels in BART's ranked set,
default deny, forbid wins. The generated policies evaluate locally (a fake
station is denied) and attach to an AgentCore Gateway in front of the
agent's MCP tools; deployment is pending. AgentCore Evaluations gets the
194 frozen cases as a ground-truth dataset and a custom code-based
evaluator that checks option equality against the label. The evaluator was
proven offline on the OpenTelemetry spans Strands really emits (the option
lives in the `gen_ai.tool.message` event of the `execute_tool Plan` span),
194 of 194 scenarios on the scripted model, before any AWS call; the
AgentCore run itself is pending.

Repo: TODO. Video: TODO.
