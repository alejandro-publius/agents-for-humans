# Devpost submission text: Last Elevator

Track: Everyday. Built with: Strands Agents SDK, Amazon Bedrock, Amazon
Bedrock AgentCore, Python, sqlite, FastMCP, OpenTelemetry.

## Inspiration

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

On July 29, 2026, disability
advocates settled a nine-year class action against New York's MTA over
subway elevator outages; the settlement requires alternate accessible
travel information at every accessibility elevator, platform announcements
every fifteen minutes, on-board announcements for outages over fourteen
days, a phone line for accessible rerouting, and real-time outage
information in the app. One plaintiff's summary of the status quo: riders
check the app before they leave the house, and the information is not
updated. BART's published goal is 98 percent elevator availability; MTA
reports 97 to 98. At that goal two of every hundred elevators are out at
any moment, and some stations need two elevators to get from street to
platform, so one outage can cut a station off entirely. The WHO counts
1.3 billion people, one in six, living with a significant disability.

Last Elevator does for one rider what that settlement now requires an
agency to do for everyone: warn, reroute, and inform in real time, using
the agency's own published policy. It automates the rider's side of the
information problem; it does not satisfy any settlement or ADA requirement.

What the feed itself says riders faced, computed from the outage archive
with the same code the laptop runs on the real one (`make impact`,
`results/outage_week.json`; fixture archive, three synthetic days, until
the laptop reruns it): 5 elevator outages at 5 stations, 52.8 elevator-hours
out, the longest 24 hours, 2 evenings with an outage in
progress at nine o'clock (when the agent asks instead of sending), and
1 station where every elevator the knowledge base lists was out at
once, which is a station a rider in a wheelchair cannot use at all.

## What it does

TL;DR: six things this agent will never do, each enforced by a Strands
hook or steering gate rather than a prompt, attacked through the full
agent 2716 times with zero leaks in four counters and a plan delivered
every time; one human moment that pauses the run with a Strands
`Interrupt` and never asks twice; the rider's own words read by the
model into a fixed vocabulary that code applies as feasibility, so a
note can take options away and never add, reorder or number them; an
evidence packet per decision;
`make tour` shows it offline in under a minute, and `make walkthrough` builds
the same outage as a page to click through with nothing installed.

It runs in the background. A poller watches BART's elevator outage feed
every five minutes. Pure code decides whether a rider's saved trip is
affected (cannot enter at origin, cannot exit at destination, or transfer)
and ranks BART's own sanctioned options in BART's published order. A
Strands agent drafts the plan and the rider message. The rider hears
nothing unless the trip is affected, and is asked something only for a
real decision: after dark, or at the last train.

What the agent will never do: assert a station not in the knowledge base,
compute minutes (in a field or in a sentence), decide affectedness on its
own, override BART's option order, send the rider a sentence it wrote
alone (every message is one of a few sentences code composes from the
policy decision and BART's own option text), or leave the rider without a
plan (at the per-run cap, code composes it).

How each guarantee is enforced, with Strands: a `BeforeToolCallEvent`
hook cancels any tool call naming a station or elevator outside the KB; a
`SteeringHandler` guides the tool call before it runs so the option is the
policy engine's top feasible option; a second gate, `steer_after_model`,
checks the final structured Plan against the policy engine and the KB and
discards the response on mismatch; structured output fixes the schema;
session state remembers rider preferences and decided cases; an
`Interrupt` pauses the run for the rider's decision after dark or at last
train. The hook plus the two steering gates are a neurosymbolic guardrail:
models propose, code decides.

The numbers that prove it (every one from `results/`, checked by CI):
policy agreement enforced versus no-steering on two models, TODO (live
rows pending); red team, 140 adversarial runs across seven attack kinds
including an injected hostile sentence and a model that never complies,
hostile stations, options, minutes and unapproved sentences that reached
the rider 0, 0, 0, 0, every run still delivered a plan, and exhaustively
every one of the 194 frozen cases times every attack, 2716 runs, the same
zeros (fixture run, pending the rerun on the real KB); feedback that a
rule-following stand-in model acts on to reach the policy engine's plan on
all 1746 persona-case runs within 5 model calls (a stand-in, not a live
model); an ablation that removes one gate at a time: with every gate no
run leaks, without the after-model gate 120 of 140 runs leak, without
only the approved-sentence check every injected sentence reaches the
rider, and every configuration still delivers a plan (fixture run);
claims verified by CI, 41 at last report plus 84 in the dispatch
package;
axe accessibility audit of the rider app, zero violations, and of every
page of the evidence site, zero violations (`make site-a11y`); quiet metric,
"7 days, 2 interruptions, 2 decisions" for three synthetic riders
(synthetic week, pending the archive replay).

Strands' own steering benchmark reports prompt-only agents at 82.5
percent, hard-coded workflows at 80.8 percent, and agents with steering
handlers recovering from every mistake; our enforced versus no-steering
eval reproduces that benchmark's shape on a real transit policy, and the
convergence study shows the recovery path is paved: every gate message
names the fix.

The human moment: the decision card carries BART's option, the added
minutes from the policy engine, the flags, the source URL and the
rejected options with one-line reasons; with the trace of which gate
fired, it is an evidence packet for the decision. Once answered, the same
case never interrupts again; if the elevator comes back first, the
question is withdrawn; if nobody answered by morning and the elevator is
still out, the question is superseded and the daytime plan goes; a
decision belongs to its outage, so the next outage of the same elevator
asks afresh; and one
outage is one message, so a rider is never told twice, five minutes
apart, about the same elevator, and a double tap on an answer gets back
what was delivered rather than an error. The card is in plain words a
screen reader can say, with the station's name rather than a code.

## How we built it

Strands Agents SDK 1.55.1: tools and a system prompt, hooks for
deterministic checks, steering before the tool and after the model,
structured output, session persistence, Interrupt for the human moment,
OpenTelemetry traces with named gate events. The knowledge base holds 194
labeled options across 97 elevators at 50 stations, read from BART's
station pages and frozen at tag `kb-labels-v1`. Evals: policy agreement
on the 194 frozen cases, enforced and no-steering, per model. AgentCore:
Runtime (the same agent builder behind `/invocations`, the contract
served by the real SDK app in an in-process test), Cedar policies
generated from the frozen KB for AgentCore Policy (deployment pending
run), a 194-case ground-truth dataset with a custom option-equality
evaluator for AgentCore Evaluations (run pending), AgentCore Memory as
the durable store for the rider's decisions, deliveries and open
questions (one event each, expiring with the retention rule; deployment
pending run), and Observability (the gate events on the OTLP trace);
every planned call validated against the service model botocore ships
before it is made. A rider app, a weekly quiet report, preference
memory, an archive with two human labelers, and a public outage dataset
export.

The two-model policy-agreement table, when the live rows land, is the
case for architecture over model choice: the gates, not the model, carry
the guarantee.

Strands surface used, one row per guarantee:

| Guarantee | Strands surface |
|---|---|
| No station or elevator outside the KB, in any tool call | `HookProvider` on `BeforeToolCallEvent`, `event.cancel_tool` |
| The option is the policy engine's top feasible option | `SteeringHandler.steer_before_tool` returning `Guide` |
| The final plan matches the policy engine, the KB and an approved sentence | `SteeringHandler.steer_after_model` returning `Guide`, so the response is discarded and the model retries |
| The plan has a fixed schema | `Agent(structured_output_model=Plan)` |
| A human decides after dark and at last train | `steer_before_tool` returning `Interrupt`; resume with an `interruptResponse` turn |
| The same case never interrupts twice | `agent.state` persisted by `FileSessionManager` |
| Bounded model calls; the rider always gets a plan | a `Model` wrapper counting calls, plus a code-composed plan at the cap |
| Every gate decision is on the trace, and in CloudWatch when deployed | the OpenTelemetry spans Strands emits, plus custom span events, through AgentCore Observability |
| The evaluator reads what the agent did | an AgentCore Evaluations custom evaluator over the session spans |
| The tool surface is governed outside the process | AgentCore Policy, Cedar generated from the frozen KB |
| Hosted the same way it is tested | an AgentCore Runtime entrypoint over the same agent builder |
| A decision, what was sent, and an open question outlive the runtime session | AgentCore Memory: one event per decision, delivery and card under the rider's actor id, read back by case key, expiring with the retention rule (deployment pending run) |
| The live path is exercised before it runs, and every retry is sendable | the real `BedrockModel` over a stand-in client that enforces the Converse rules; the cap wrapper makes each request sendable at the first attempt |
| The rider's own words become constraints, never orders | `structured_output_model=RiderNote`: a fixed vocabulary with the rider's words as the quote; code drops a quote the note does not contain and applies the rest as feasibility only |

## Challenges we ran into

The first steering gate caught wrong options before the tool ran, but a
model can still write the wrong option into the final plan; a second gate
after the model closed that gap. A hostile sentence with no numbers and no
codes passed every field check, so the rider message became a choice
among code-composed sentences. A model that never complied looped without
limit, because the after-model retry loop in Strands 1.55.1 runs inside
one turn; a per-run cap and a code-composed plan at the cap closed that.
Interrupt semantics on decline needed a definition: the plan stays on file
with BART's values and status "hold".
The mock model echoes the label, so its no-steering number proves
plumbing, never behavior; only the live rows count. Every AWS step became
a dry-run target with a documented permission list so the offline build
never needed a key. The last challenge was reaching the live path without
a key at all: the agent runs through Strands' real Bedrock adapter with a
stand-in client that enforces the Converse rules and plays a model that
reads the conversation. That stand-in found three things the scripted
models never could: a runtime prompt that named no trip, a hook message
that named no right value, and a resumed pass that could ask the rider
twice; every AWS call the apply paths make is also validated against the
service model botocore ships before it is made.

## Accomplishments that we're proud of

Zero hostile stations, options, minutes or unapproved sentences reached
the rider across 140 adversarial runs and 2716 exhaustive runs, and every
run still delivered a plan (fixture run; laptop rerun pending). We then
removed the gates one at a time and showed which one does the work, so
the zeros are a measurement, not a hope. The custom AgentCore evaluator
was proven on real Strands OpenTelemetry spans before any AWS call. The
same harness ran a synthetic second agency, with other station codes and
another published option order, through every stage with zero code
changes, and through the hosted contract: its 48 cases through the same
runtime entrypoint, every counter 48 of 48. Five findings about the SDK went back to its maintainers with
an offline reproduction that runs as a test; one of them, the
tool-result separator applied only after a rejection, is measured on the
wire and fixed in the cap wrapper, and another, two retry layers stacked
under a throttle, is switched off at the client so every retry on the
live path is one the trace shows. The hosted contract was then run over
the whole dataset offline: every case through the runtime entrypoint
with five riders each, the plan the model's with the policy engine's
option every time, one question per night, one message per outage, a
note that only gives orders changing nothing every time and a note with
a real constraint taking one option away and nothing else. The live path was rehearsed end to end
without a key: the exact request on file, every retry accepted at the
first attempt, every persona converging in both tool-result formats, the
human moment asking once. A threat model lists what we do
not defend as plainly as what we do. Real users: TODO (count and one line
each). A public dataset of BART elevator outages at five-minute
resolution: TODO rows once exported from the archive.

## What we learned

Make the agent more deterministic. A guardrail that only inspects the tool
call is half a guardrail; the final response needs its own gate. Fail
closed. Cite numbers only from files that CI checks.

Two gaps we would not have found without a red team that runs the full
agent. First, field checks are not enough: a hostile sentence with no
numbers and no station codes, the kind an outage feed or a station page
could inject, passed every check on every field, so the rider message is
now a choice among sentences code composed. Second, a retry is not a
bound: in Strands 1.55.1 a steering `Guide` after the model retries
inside one turn with no counter, so a turn limit never fires on a model
that never complies; the fix is a per-run cap on model calls with a
code-composed plan at the cap, and the finding is written up with an
offline reproduction for the SDK's maintainers, together with a smaller
one: a steering handler that raises is treated as `Proceed`, so a gate
that must fail closed has to catch its own errors and return `Guide`.
Ours do, and a test proves both behaviours. A third, found while
hardening the live path: two rejections in a row leave two adjacent user
turns, which Bedrock's alternating-roles rule would reject; the same
wrapper that caps the calls folds them before the model sees them.

Run the live path before you can run it live. The agent goes through
Strands' real Bedrock adapter with a stand-in client that enforces the
Converse rules and replays scripted chunks, so the exact request Bedrock
will receive is on file, every retry is known to be sendable at the
first attempt, and a permission error, a throttle or a truncated
response each cost what the evidence says they cost. It also measured
one more thing: the SDK's tool-result separator is applied only after
Bedrock has rejected a request once, so the wrapper applies it ahead of
time and the rejected round trip is gone.

Ablate your own gates. Removing them one at a time showed which one
protects the rider (the gate after the model), which check covers another
(approved sentences cover the prose checks), and a feedback gap the red
team could not see: the plan gate's "not in the knowledge base" reason
did not say what the right value was, so a model reading only that gate
could never fix a wrong elevator. It does now, and the test that proves
it runs with the before-tool gates switched off.

And one thing about the human moment: the useful unit of memory is the
decision, not the conversation. Storing the rider's answer per case in
session state is what lets the agent stay quiet for a week.

The rider's own words are the one input that is neither a fact nor a
decision. The safe shape for them turned out to be a fixed vocabulary
the model may only point at, with the rider's own quote as the reason,
applied by code as feasibility and nothing else; a note can then take an
option away and never add, reorder, name or number one. Sent through the
whole hosted contract for every case, a note that gives orders changes
nothing, and the sweep counts it.

Rehearse the day after the merge, not only the merge. Running the main
repo's CI workflow in the integrated layout, and walking the last day's
checklist step by step against every rule the docs check enforces, found
one after another the things that would have gone red at the worst hour:
a compiled test file a scratch repository listed, rules that required
the literal TODO the owner was about to replace, and a determinism check
that would have compared real numbers with fixture ones once the real
results landed. The fix that generalizes: a results writer has to know
whether its run was real, and a fixture run must never overwrite a file
a real run wrote.

## What's next for Last Elevator

Live rows for two models, the AgentCore Policy deployment, the AgentCore
Evaluations run, the AgentCore Memory resource for the decisions, the
deliveries and the open questions (the retention rule for what the agent
keeps about a rider exists; the archive's is next). Real riders' saved
trips through the archive's week (`make report` takes them today; the
synthetic riders stand in until then), and a note vocabulary that grows
from what riders actually write, one fixed kind at a time, never a free
field. Then a real second agency: the harness is agency-agnostic today
(a synthetic one runs through every stage in the test suite, and through
the real Bedrock adapter with a model that reads the conversation), so
the work is a station KB, two labelers and a feed parser, and the
onboarding guide says exactly that.

## Screenshots (docs/screenshots/, numbered)

00 the first shot, one run in plain lines arriving one per frame, as a
GIF with its last frame as a still (`make first-shot`); 01 the decision
card as the rider sees it (`make demo-one-after-dark`);
02 the weekly quiet report, its opening line first (`make report`, a
synthetic week until the archive replay); 03 every gate as a span event
on the trace (`make demo-one-trace`); 04 the policy-agreement table
(`make results-table`; the mock rows say plumbing proof, the live rows
come from `make eval-live`); 05 the red-team counts (`make red-team`,
fixture run until the laptop reruns it); 06 the architecture, one poll
for one rider (`make diagrams`); 07 the claims badge (`make badge`);
08 the rider app's axe audit (the main repo's accessibility target); 09 the
AgentCore Evaluations dataset, its statistics and the first scenario. The index
with each image's source and who regenerates it is
`docs/screenshots/README.md`.

## Links

- Repo: TODO (public, MIT license)
- Video: TODO (under five minutes)
- Live URL: TODO
- Evidence site: TODO (GitHub Pages, published by `make site` on every push to main once Pages is on)
- Click-through walkthrough (no install, one outage end to end, the decision card answerable): https://claude.ai/code/artifact/a219b4a5-2c35-42b1-b708-65934193901b
- The questions a judge asks, answered with what proves each: `docs/FAQ.md` in the repo (a page on the evidence site)
- AgentCore runtime ARN: TODO
- Builder ID email: in the form
- Posts: TODO, TODO, TODO

## Disclosure

All code was written between August 10 and September 14, 2026 with AI
coding assistants. Pre-existing code: none known (TODO confirm).
