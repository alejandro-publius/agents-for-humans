# README sections to merge into agents-for-humans/README.md

Order, per the field notes: what the agent will never do, how each
guarantee is enforced, the numbers that prove it, the human moment, then
the product, the impact narrative, the challenges. A judge who reads only
the first paragraph should know this is not a chat wrapper. Every number
is from `results/` or marked TODO; fixture-run numbers say so.

---

## Last Elevator

A BART rider who depends on elevators is stuck checking outage alerts and
re-planning the same trip, over and over. Last Elevator does that work in
the background: it watches BART's elevator feed, decides in code whether
her saved trip is affected, and tells her before she leaves the house, in
BART's own words, the option BART publishes for that station, in BART's
order, with the minutes BART's policy implies, in a sentence code
composed. It stays quiet unless a trip is affected, and asks instead of
sending only when a person should decide: after dark, or at the last
train. Then the run pauses on a Strands `Interrupt` and she gets a card
with BART's option, the minutes, the page they came from, and the options
it rejected with reasons; it never asks twice, and it withdraws the
question if the elevator comes back first. Six things the agent will
never do are enforced by Strands hooks and steering gates rather than by
prompts, and were attacked 2716 times through the full agent with zero
leaks in four counters. Every number below comes from a file in
`results/` and is checked again on every commit.

Built with the Strands Agents SDK (1.55.1). Models propose, code decides.

![One run in plain lines, arriving one per frame: code decided, the model tried three times, a hook and two gates stopped it, what reached the rider, in a sentence code composed from BART's wording](docs/screenshots/00-first-shot.gif)

`make demo-one-brief` prints those lines; `make first-shot` renders them.

> **TL;DR for a judge with two minutes.** Six things this agent will never
> do, each enforced by a Strands hook or steering gate rather than a
> prompt, each attacked through the full agent (2716 exhaustive runs, zero
> leaks in four counters, a plan delivered every time), one human moment
> that pauses the run with a Strands `Interrupt` and never asks twice, an
> evidence packet per decision, and the live path exercised through
> Strands' real Bedrock adapter before the first live call. `make tour`
> shows all of it offline in under a minute; `make verify` checks 84 claims
> against `results/` on every commit. Fixture-run numbers are labelled
> as such until the laptop reruns them on the real KB and policy engine.

**What the agent will never do.** Assert a station or elevator that is
not in the knowledge base, in a field or in a sentence. Compute minutes,
in a field or in a sentence. Decide by itself whether a trip is affected.
Override BART's option order. Send the rider a sentence it wrote alone:
every outbound message is one of a few sentences code composes from the
policy decision and BART's own option text. Leave the rider without a
plan: if the model never produces an approved plan within the per-run
cap, code composes it.

**How each guarantee is enforced.** A `BeforeToolCallEvent` hook cancels
any tool call naming a station or elevator outside the KB (the cancel text
lands in the tool result). A `SteeringHandler` guides the tool call before
it runs: the option must be the policy engine's top feasible option. A
second gate, `steer_after_model`, checks the final structured Plan
against the policy engine and the KB and discards the response on
mismatch, so the model retries. Structured output fixes the schema.
Session state remembers rider preferences and decided cases. The gates
fail closed. Together the hook and the two steering gates are a
neurosymbolic guardrail: the model proposes, code decides.

**Strands surface used.** One row per guarantee; every path exists in the
dispatch package and `make check-docs` verifies that it does.

| Guarantee | Strands surface | Where |
|---|---|---|
| No station or elevator outside the KB, in any tool call | `HookProvider` on `BeforeToolCallEvent`, `event.cancel_tool` | `le_dispatch/gates.py` (`KBHook`) |
| The option is the policy engine's top feasible option | `SteeringHandler.steer_before_tool` returning `Guide` | `le_dispatch/gates.py` (`PlanGateHandler`) |
| The final plan matches the policy engine, the KB and an approved sentence | `SteeringHandler.steer_after_model` returning `Guide` (the response is discarded and the model retries) | `le_dispatch/gates.py` (`check_plan`), `le_dispatch/messages.py` |
| The plan has a fixed schema | `Agent(structured_output_model=Plan)`, `result.structured_output` | `le_dispatch/plan.py` |
| A human decides after dark and at last train | `steer_before_tool` returning `Interrupt`; `result.interrupts`; resume with an `interruptResponse` turn | `le_dispatch/interrupts.py` (`DecisionInterruptHandler`) |
| The same case never interrupts twice; no re-ask while an answer is pending | `agent.state` persisted by `FileSessionManager` | `le_dispatch/interrupts.py` (`DecisionMemory`, `Inbox`) |
| Bounded model calls; the rider always gets a plan | A `Model` wrapper counting `stream` calls, plus a code-composed plan at the cap | `le_dispatch/budget.py` (`BudgetedModel`), `le_dispatch/gates.py` (`deliver`) |
| Every gate decision is on the trace, and in CloudWatch when deployed | OpenTelemetry spans Strands emits (`execute_tool`, `gen_ai.tool.message`) plus custom span events; the OTLP exporter for AgentCore Observability when the runtime provides an endpoint | `le_dispatch/tracing.py`, `le_dispatch/evidence.py`, `infra/agentcore/runtime/entrypoint.py` |
| The evaluator reads what the agent did, not what it said | AgentCore Evaluations custom code evaluator over `sessionSpans` | `le_dispatch/evaluators/option_equality.py`, `le_dispatch/spans.py` |
| The tool surface is governed outside the process | AgentCore Policy (Cedar) generated from the frozen KB, evaluated locally | `le_dispatch/cedar_gen.py` |
| Hosted the same way it is tested | AgentCore Runtime `BedrockAgentCoreApp` entrypoint over the same `build_agent`; `/ping` and `/invocations` served by the real SDK app in an in-process test | `infra/agentcore/runtime/entrypoint.py` |
| A decision, what was sent, and an open question outlive the runtime session | AgentCore Memory: one event per decision, delivery and card under the rider's actor id (`create_event`), read back by case key (`list_events` with a metadata filter), expiring with the retention rule; every call validated against the service model as the tests make it | `le_dispatch/agentcore_memory.py` (`AgentCoreDecisionStore`, `AgentCoreSentStore`, `AgentCoreCardStore`), `le_dispatch/interrupts.py` (`DecisionMemory`, `SentLog`, `Inbox`) |
| The live path is exercised before it runs, and every retry is sendable | The real adapter (`BedrockModel.format_request`, `BedrockModel.stream`, its exceptions) over a stand-in client that enforces the Converse rules; the cap wrapper makes each request sendable at the first attempt | `le_dispatch/bedrock_wire.py`, `le_dispatch/budget.py` (`sendable_turns`), `docs/evidence/bedrock-wire.md` |
| The rider's own words become constraints, never orders | `Agent(prompt, structured_output_model=RiderNote)`: the model may only return kinds from a fixed vocabulary with the rider's words as the quote; code drops a quote the note does not contain and applies what is left as feasibility only | `le_dispatch/note.py` (`RiderNote`, `check_quotes`, `apply_constraints`), `infra/agentcore/runtime/entrypoint.py` |

**The numbers that prove it.**

- Policy agreement, enforced versus no-steering, two models: TODO (live
  rows land from `make eval-live` on the laptop; the mock rows are
  plumbing proof only and are never presented as an ablation result). The
  same rows carry model calls and tokens per mode, so the price of
  enforcement sits next to its agreement, and every evidence packet states
  what its one decision cost.
- Red team: 140 adversarial runs across seven attack kinds (fake
  stations, wrong options, invented minutes, invented minutes in prose,
  fake stations in prose, a hostile sentence injected as if through the
  feed, and a model that never complies) through the full agent; hostile
  stations, options, minutes and unapproved sentences that reached the
  rider: 0, 0, 0, 0; every run still delivered a plan, 20 of them composed
  by code when the model never complied (`results/red_team.json`; fixture
  run in the dispatch sandbox, pending the laptop rerun on the real KB and
  policy engine). Exhaustively: every one of the 194 frozen cases times
  every attack, 2716 runs, the same zeros
  (`results/red_team_exhaustive.json`).
- Feedback is actionable: a rule-following stand-in model that starts
  wrong (nine personas, from a wrong station to an injected sentence to
  everything wrong at once) reaches the policy engine's plan on all 1746
  persona-case runs within 5 model calls
  (`results/adaptive_convergence.json`; a stand-in, not a live model; the
  live rows are the result).
- Which gate protects what: the same 140 attacks with each gate removed
  in turn (`results/gate_ablation.json`, fixture run). With every gate,
  no run leaks. Remove the after-model gate and 120 of 140 runs leak (20
  fake stations, 40 wrong options, 80 wrong minutes, 80 unapproved
  sentences reach the rider). Remove only the approved-sentence check and
  every injected sentence reaches the rider (20 of 20). Remove only the
  prose checks and nothing leaks: the approved-sentence check covers them
  for what reaches the rider; they stay because their reasons name the
  exact problem. Remove both before-tool gates and nothing leaks either:
  they are the in-process twin of the gateway's Cedar policy and the
  reason a hostile tool call never runs, not the rider's last line. Every
  configuration still delivered every plan.
- The live path, offline: the agent through Strands' real Bedrock
  adapter with a stand-in client that enforces the Converse rules
  (`docs/evidence/bedrock-wire.md`, `results/bedrock_wire.json`; the
  stand-in replies with scripted chunks or plays a model that reads the
  conversation, so this measures the request path, never a live model).
  The request Bedrock will receive is on file
  (`docs/evidence/bedrock-request.json`). Every gate then two Guides in a
  row: six requests, none rejected; left to the SDK's lazy tool-result
  separator, one request is rejected first; with no pass at all the second
  Guide is unsendable and code composes the plan. A permission error or a
  response cut off by the token limit or a stream silent past the read
  timeout costs one call and the rider still gets the plan; a throttle is
  retried on one layer (the client's own
  retries are off and the SDK's are bounded, so a throttled call costs
  at most four requests and fourteen seconds); a prose answer is
  followed by the SDK's forced structured-output request. After dark the rider is asked
  once and the resumed pass, retried by the gates, ends sent or held with
  the model's plan. Every convergence persona reaches the plan through
  the adapter in both tool-result formats (Anthropic's JSON with a status
  flag, Nova's text without one): 432 of 432 runs on a 24-case slice,
  within 5 calls, no request rejected (`results/wire_convergence.json`).
  And the hosted contract over the whole dataset: every one of the 194
  cases through the runtime entrypoint with five riders each (daytime;
  daytime with a note that only gives orders; daytime with a note that
  names a real constraint and gives orders too; after dark, never
  answers; after dark, says no), 2328 invocations, 970 model runs, 0
  composed by code: the daytime plan carries the policy engine's option
  and minutes 194 of 194 times, the next poll sends nothing new, the note
  that gives orders changes nothing 194 of 194 times and the note with a
  real constraint takes one option away and nothing else 194 of 194
  times, after dark the rider is asked once and the morning poll sends
  and closes the question, a no is held, and once the elevator is back
  and out again the rider is asked afresh; the Memory stand-in's
  every call well formed (`results/runtime_sweep.json`, fixture run).
- Claims verified by CI: 41 at last report in the main repo, plus 84 in
  the dispatch package (`make verify`), TODO combined count after merge.
- Accessibility: axe audit of the rider app, zero violations
  (`results/axe.json`); and of the evidence site a judge reads, every
  page through axe-core in Chromium, zero violations, as a claim
  (`results/site_a11y.json`, `make site-a11y`).
- Quiet: "7 days, 2 interruptions, 2 decisions" for three synthetic
  riders (`results/quiet.json`; synthetic week, pending the archive
  replay).

Strands' own steering benchmark reports prompt-only agents at 82.5
percent, hard-coded workflows at 80.8 percent, and agents with steering
handlers recovering from every mistake; our enforced versus no-steering
eval reproduces that benchmark's shape on a real transit policy.

**The human moment.** After dark or at last train, the run pauses with a
Strands `Interrupt`. The rider gets a decision card: BART's option, the
added minutes from the policy engine, the flags, the source URL, and the
rejected options with one-line reasons. The answer is stored in session
state, so the same case never interrupts twice, and while the rider has
not answered, the next poll does not ask again. One outage is one
message: a plan already sent is not sent again while the outage lasts,
and no model runs for the repeat. If the elevator comes back before the
rider answers, the question is withdrawn, not left hanging. If the
runtime session is recycled while a question is open, the next session
finds the card in AgentCore Memory and reports it pending rather than
asking again. A question never blocks and an answer never fails: when
the outage is still on in the morning and nobody answered the night's
question, the rule that asked no longer holds, so the question is
closed as superseded and the plan goes the way any daytime plan does;
a tap repeated, a mind changed after a decline, or an answer to a
question this container never asked each gets a plain state back (what
was delivered, or the plan drafted under the answer), never an error.
A decision belongs to its outage: when the elevator comes back, the
answer is forgotten in every copy (the mirror, the session, Memory), so
the next outage of the same elevator asks afresh instead of being held
or sent on last month's answer, and the conversation goes with the
outage too: the trip's session is deleted when nothing is out, so the
next outage starts clean and nothing accumulates about a rider.
The card is in plain words a screen reader can say, with the station's
name when the knowledge base has one. The card with its source URL and
the trace of which gate fired is the evidence packet for that decision.

**The rider's own words.** A rider can say, in plain words, what they
cannot do today: no ramps, no stairs, no bus tonight. The model reads
the note (Strands structured output), and the only thing it may return
is a constraint from a fixed vocabulary with the rider's own words as
the reason; code checks the words are really in the note, drops the
rest, and applies what is left as feasibility only: the ruled-out
option is marked infeasible, BART's order among the rest stands, the
minutes stay the policy engine's, and if nothing is left the note is set
aside and the card says so. A note can take options away; it can never
add one, reorder them, name a station or change a number, so a note that
tries to give orders changes nothing (`le_dispatch/note.py`,
`make demo-one-brief DEMO_ONE_ARGS='--note "..."'`).

### The product

A poller watches BART's elevator outage feed every five minutes and diffs
snapshots into sqlite. A parser turns outage text like "DELN: Platform -
Richmond" into structured outages. A trip matcher and policy engine, pure
code with no model, decide whether a rider's saved trip is affected
(cannot enter at origin, cannot exit at destination, or transfer) and
rank BART's sanctioned options in BART's published order:
alternate_elevator, backtracking, transit, mitigation_trip,
mitigation_shuttle. The knowledge base holds 194 labeled options across 97
elevators at 50 stations, read from BART's station pages and frozen at tag
`kb-labels-v1` (55 alternate_elevator, 53 backtracking, 86 transit).
alternate_elevator means an alternate accessible path at the same station,
including ramps, lifts and tunnels. A Strands agent drafts the plan and
the rider message. There is a rider app, a weekly quiet report, preference
memory, and an archive with two human labelers.

AgentCore: Runtime (the same agent builder behind `/invocations`, the
contract served by the real SDK app in an in-process test), Policy (Cedar
generated from the frozen KB, evaluated locally, deployment pending run),
Evaluations (194-case ground-truth dataset, custom option-equality
evaluator proven on real Strands spans, 194 of 194 scenarios locally on
the scripted model, AgentCore run pending), Memory (the rider's
decisions, deliveries and open questions as events expiring with the
retention rule, so a recycled runtime session neither asks twice nor
sends twice; best effort, so a Memory outage degrades the durable copy
and never fails a delivery, with the failed writes replayed once it is
back; deployment pending run) and Observability (the gate events
on the OTLP trace when the runtime provides an endpoint) are scaffolded,
with every planned call validated against the service model botocore
ships; see `docs/RUNBOOK.md`. Runtime ARN: TODO. Live URL: TODO.

### Why this matters beyond BART

On July 29, 2026, disability advocates settled a class action filed in
2017 against New York's MTA over subway elevator outages. The settlement
requires alternate accessible travel information at every accessibility
elevator, platform announcements every fifteen minutes about long-term
outages, on-board announcements for outages lasting more than fourteen
days, a phone line for accessible rerouting help, and real-time outage
information in the MTA's app. One plaintiff's summary of the status quo:
riders check the app before they leave the house, and the information is
not updated. Last Elevator does for one rider what that settlement now
requires an agency to do for everyone: warn, reroute, and inform in real
time, using the agency's own published policy. It automates the rider's
side of the information problem; it does not satisfy any settlement or
ADA requirement, and we do not claim it does.

What the feed itself says riders faced, computed from the outage archive
with the same code the laptop runs on the real one (`make impact`,
`results/outage_week.json`; fixture archive, three synthetic days, until
the laptop reruns it): 5 elevator outages at 5 stations, 52.8 elevator-hours
out, the longest 24 hours, 2 evenings with an outage in
progress at nine o'clock (when the agent asks instead of sending), and
1 station where every elevator the knowledge base lists was out at
once, which is a station a rider in a wheelchair cannot use at all.

The availability numbers are the same everywhere: MTA reports 97 to 98
percent a month, BART's published goal is 98 percent. At that goal two of
every hundred elevators are out at any moment, and some BART stations need
two elevators from street to platform, so one outage can cut a station off
entirely. The WHO counts 1.3 billion people, one in six worldwide, living
with a significant disability. Chicago's CTA already posts system-wide
elevator outages at each station because riders need to know before they
board whether they can exit at their destination. BART today; the same
harness plus a new station KB applies to any agency with an elevator feed
and a published policy (`docs/ONBOARDING-AN-AGENCY.md`; a synthetic second
agency runs through every stage in the test suite with zero code changes,
and through the hosted contract: its 48 cases through the same runtime
entrypoint, five riders each, every counter 48 of 48, `make
runtime-sweep-synthetic`, `results/runtime_sweep_synthetic.json`).

Sources: DRA press release (https://dralegal.org/press/ny-subway-elevators-settlement/),
amNY (https://www.amny.com/nyc-transit/mta-and-disability-groups-elevator-accessibility/),
WHO (https://www.who.int/news-room/fact-sheets/detail/disability-and-health),
BART elevator pages (https://www.bart.gov/guide/accessibility/elevators),
CTA elevator status (https://www.transitchicago.com/travel-information/elevator-status/).

### Challenges

The first steering gate caught wrong options before the tool ran, but a
model can still write the wrong option into the final plan; the second
gate after the model closed that gap. Then the red team found that a
hostile sentence with no numbers and no station codes (the kind an outage
feed or a station page could inject) passed every field check; approved
sentences closed it, and the model now only picks among sentences code
composed. Then a model that never complied looped without limit: in
Strands 1.55.1 the after-model retry loop runs inside one turn, so a turn
limit never fires; a per-run cap on model calls and a code-composed plan
at the cap closed that, and the finding is written up with an offline
reproduction for the SDK's maintainers (`docs/UPSTREAM-NOTE.md`).
The ablation study then showed that the plan gate's "not in the knowledge
base" reasons did not name the right value, so a model that only read
that gate could never fix a wrong elevator; every reason now names the
right value, and the plan gate alone leads the stand-in model to the plan.
Interrupt semantics on decline needed a definition
(the plan stays on file with BART's values and status "hold"). The mock
model echoes the label, so its no-steering number proves plumbing, never
behavior; the live rows are the result. The dispatch package was built
without access to the repo, so every repo dependency became a documented
interface with a fixture.

### Security

Tests refuse the network: `socket.getaddrinfo` and
`socket.create_connection` are patched to raise, and a fixture strips
every live key name from the environment for every test. `make verify`
runs a secret scan over tracked files. No keys exist in the repo; there
is no `.env`. Everything runs offline on the mock provider and fixtures;
the AWS targets run only with credentials and an explicit `--yes`. The
threat model (`docs/THREAT-MODEL.md`) says what is trusted, what is not,
which gate stops each threat with the test and the ablation row that
prove it, and which threats are not defended and what stands in.

### Disclosure

All code was written between August 10 and September 14, 2026 with AI
coding assistants. If any file predates August 10 or was copied from
another repository, it is listed here: TODO (none known).

### For a judge with five minutes

`make judge` (two to three minutes, offline, no key): `make verify`, then the
tour (every gate fires on a misbehaving model, the human moment pauses
and resumes, the counts), the ablation table, the live path through the
real Bedrock adapter with a stand-in client, the runtime's every state.
`make walkthrough` builds one outage end to end as a page with nothing
installed, four scenes from the committed evidence packets, with the
decision card you answer yourself; the hosted copy is at https://claude.ai/code/artifact/a219b4a5-2c35-42b1-b708-65934193901b
Then `docs/FAQ.md` (the questions a judge asks, each answer pointing at
what proves it), `docs/EVIDENCE.md` (every guarantee with its code, test,
span event, results file and claim id), and `docs/evidence/DELN-E1-daytime.md`
(one decision as an evidence packet with its sequence diagram). A judge
who reads instead of runs: `docs/TOUR-TRANSCRIPT.md` is what `make judge`
prints, regenerated and diffed in CI; the evidence site (its URL is in
the placeholders below) is every one of these documents as a page.

### Testing

`make demo-one` runs offline on the mock provider; no credentials
required. `make demo-one-trace` renders the gate span events; `make
demo-one-after-dark` shows the pause and the resume; `make tour` runs
all three plus the counts, and `make judge` adds `make verify` and the
ablation table (two to three minutes); `docs/TOUR-TRANSCRIPT.md` is what they
print, regenerated and diffed in CI. `make demo-live` puts one case through the
same gates on a live Bedrock model and writes an evidence packet (dry run
by default; the laptop passes `DEMO_LIVE_ARGS="--yes"`). Live link: TODO.

### Submission placeholders

- Video URL: TODO
- Live URL: TODO
- Evidence site URL: TODO (GitHub Pages, once Pages is on)
- The claims badge (from this package's README, first line): replace TODO_OWNER and TODO_REPO in its URL
- AgentCore runtime ARN: TODO
- Builder ID email: TODO (goes in the form, not in the repo)
- Post URLs (builder.aws.com): TODO, TODO, TODO
