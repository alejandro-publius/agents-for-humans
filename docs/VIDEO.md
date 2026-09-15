# Video script (under 5 minutes)

Numbers are claim markers rendered from `results/`; TODO marks what is not measured yet.
Strands Agents and Amazon Bedrock AgentCore are named on screen in the title card and the closing card.

## 0:00 The number (title card: "Last Elevator, built with Strands Agents")

"On the demo rider's synthetic weekend, per-station BART alerts would have sent
<!-- claim:interruptions.rider.bart_style_station_alerts -->6 messages. Last Elevator sent
<!-- claim:interruptions.rider.interruptions_sent -->4 each with a workaround. TODO: replace with the
real weekend numbers from the archive."

## 0:20 The problem, who it is for, why it matters

Screen: BART's Elevator Status page. Voice: elevator-dependent riders, the ADA settlement, the New
York analogue (links in docs/strategy.md). "BART tells you an elevator is out. It does not tell you
what to do about your trip."

## 0:55 A real outage flowing to a real plan (screen recording of `make replay` and the app)

Screen: `results/replay.md`, then the rider app inbox. Voice: the rider registered San Leandro to
Embarcadero once. The San Leandro platform elevator went out. The agent looked up BART's own
documented option for that elevator, ranked it first, computed the minutes from the schedule, and
sent one message. TODO: use a real outage from the live archive instead of the synthetic one.

## 1:50 Why it needs an agent, and why code decides (screen: `make demo-one`)

Screen: the demo output. Voice: the model proposes; the policy engine decides. Three tools, a
hook, a steering handler, a structured plan. Point at the hook cancelling a made-up station and the
steering handler guiding a wrong option back to BART's order.

## 2:40 The guardrails under attack (screen: `make red-team`)

"<!-- claim:red_team.runs -->20 adversarial runs. Fake stations, wrong options, invented minutes.
<!-- claim:red_team.reached_rider.hallucinated_stations -->0<!-- claim:red_team.reached_rider.wrong_options -->0<!-- claim:red_team.reached_rider.minutes_not_from_policy -->0 reached the rider."

## 3:15 The human decision (screen: `make demo-one ARGS=--after-dark`, then the decision card in the app)

Voice: after dark and past the last train the run pauses on a Strands Interrupt. The rider sees
BART's option, the minutes, the source page, and every rejected option with a reason. Accept, and the
run resumes; the answer is remembered.

## 4:00 What is simulated, and what is measured live

Voice: the model in these evals is scripted; the live policy-agreement numbers on Amazon Bedrock are
TODO (E9). The schedule minutes are synthetic fixtures. The Mitigation Trip is drafted, not placed.

## 4:30 Closing card

"Built with Strands Agents, Strands Evals and Amazon Bedrock AgentCore (TODO: deployment). Code, evals
and every number: github.com/alejandro-publius/agents-for-humans."
