# Devpost submission text: Last Elevator

Every number below is a `<!-- claim:key -->` rendered from `results/` by `make render-claims` and
checked by `scripts/verify_claims.py`. Anything not yet measured is marked TODO.

**Track:** Everyday Agents. **Built with:** Strands Agents SDK, Strands Evals, Amazon Bedrock
(TODO: live run), Amazon Bedrock AgentCore (TODO: deploy), Python, FastAPI, SQLite, MCP.

## What it does

Last Elevator is a background agent for BART riders who cannot use stairs or escalators. A rider
registers the trips they actually take once. The agent watches BART's elevator outage feed, and
when an outage breaks one of those trips it applies BART's own published outage options to that
route and sends one message with the workaround: the ranked option, the steps, and the minutes it
adds. Outages that do not touch the rider's trips produce silence. When the situation needs a human
call, after dark or past the last train, the run pauses on a real Strands Interrupt and the rider
gets a decision card instead of a plan.

## Who it is for

Wheelchair and scooter users, people with strollers, people with injuries, seniors: anyone for whom
a broken elevator means a broken trip. BART's own alerts tell you an elevator is out; they do not
tell you what to do about your trip.

## How it works

1. **Poll and diff.** The elevator advisory is polled every 5 minutes and diffed against the last
   snapshot in SQLite.
2. **Parse, then validate in code.** The model proposes a structured parse of BART's free text
   (`"DELN: Platform - Richmond"`); code validates it against a knowledge base built from BART's
   own accessible-path pages for <!-- claim:kb_label_distribution.stations -->50stations,
   <!-- claim:kb_label_distribution.elevators_total -->97elevators and
   <!-- claim:kb_label_distribution.options_total -->194documented outage options.
3. **Decide in code.** A pure-Python policy engine matches the outage to the trip (boarding or
   exiting, platform direction from the schedule), ranks BART's options in BART's order (alternate
   elevator, backtracking, transit, Mitigation Trip, Mitigation Shuttle), computes minutes from the
   schedule, and sets after-dark and last-train flags.
4. **Draft with guardrails.** A Strands agent with three tools drafts the message. A
   `BeforeToolCall` hook cancels any call naming a station or elevator outside the knowledge base.
   A steering handler guides `draft_message` back to the policy engine's top option and raises a
   real Interrupt when a rider decision is needed. The run ends in a structured `Plan`.
5. **Verify in code.** The plan's option, minutes and affected flag are overwritten from the
   policy engine if the model disagreed, and any station-code-shaped token the KB does not know
   replaces the message with BART's documented text.

Models propose. Code decides.

## What we measured

- Red team, <!-- claim:red_team.runs -->20adversarial runs that named fake stations, picked wrong
  options and invented minutes: <!-- claim:red_team.reached_rider.hallucinated_stations -->0hallucinated stations, <!-- claim:red_team.reached_rider.wrong_options -->0wrong options and
  <!-- claim:red_team.reached_rider.minutes_not_from_policy -->0invented minutes reached the rider.
- Policy agreement on the <!-- claim:policy_agreement.enforced.cases_run -->194documented
  options, mock mode (plumbing proof): <!-- claim:policy_agreement.enforced.agreement_pct -->100.0%
  with steering, <!-- claim:policy_agreement.no_steering.agreement_pct -->100.0% without. Live
  numbers on Amazon Bedrock: TODO (E9, runs once credentials arrive).
- Synthetic weekend replay for the demo rider: <!-- claim:interruptions.rider.interruptions_sent -->4interruptions where per-station BART alerts would have sent
  <!-- claim:interruptions.rider.bart_style_station_alerts -->6. Real weekend: TODO (archive).
- Accessibility of the rider app: <!-- claim:axe.violations -->0axe-core violations.
- Every eval case, guardrails on: <!-- claim:summary.cases_passed -->211of
  <!-- claim:summary.cases_run -->211; guardrails removed: <!-- claim:ablation.cases_passed -->209of
  <!-- claim:ablation.cases_run -->211.

## What is simulated

The model in every eval and replay is scripted (no Bedrock credentials were available during the
build). BART API responses are documented samples and labeled synthetic snapshots. Minutes come
from synthetic schedule fixtures and are labeled as such in every plan. The Mitigation Trip request
is drafted, never placed: BART requires the rider to tell a Station Agent.

## Testing instructions for judges

```bash
git clone https://github.com/alejandro-publius/agents-for-humans.git last-elevator
cd last-elevator && make setup && make replay && open results/replay.md
make demo-one                   # decision, mechanisms, plan
make demo-one ARGS=--after-dark # the Interrupt, the decision card, the resume
make app                        # http://127.0.0.1:8000
```

No keys are needed for any of the above. Live demo URL: TODO (deploy is a human decision).
Video: TODO. Architecture diagram: TODO (export from docs/strategy.md).
