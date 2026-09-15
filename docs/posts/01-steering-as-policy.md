# Agents for Humans: turning BART's elevator policy into a Strands steering handler

_Draft for builder.aws.com. Title keeps "Agents for Humans". Numbers are claim markers from `results/`._

BART publishes, for every station, what to do when a specific elevator is out: take the other
platform elevator, ride one stop and come back, take a bus, ask the Station Agent for an accessible
van. That is a ranked policy written by the operator. The interesting engineering question was how
to make a language model follow it without trusting the model to remember it.

## The mechanism

The Strands Agents SDK ships a steering plugin. A handler subclasses `SteeringHandler` and
implements `steer_before_tool`. Return `Proceed` and the tool runs. Return `Guide(reason=...)` and
the tool call is cancelled, the reason goes back to the model as feedback, and the model retries.

Our handler holds one value computed by code, the first feasible option in BART's order for this
outage and this trip, and guides `draft_message` whenever the model proposes anything else. The
policy never lives in the prompt. It lives in a knowledge base scraped from BART's own pages
(<!-- claim:kb_label_distribution.stations -->50 stations, <!-- claim:kb_label_distribution.options_total -->194 documented options) and in a pure-Python engine that ranks feasibility, computes minutes and sets
the after-dark and last-train flags.

## What it bought us

- Under a red team of <!-- claim:red_team.runs -->20 adversarial runs (fake stations, wrong
  options, invented minutes), <!-- claim:red_team.reached_rider.wrong_options -->0 wrong options
  and <!-- claim:red_team.reached_rider.hallucinated_stations -->0 hallucinated stations reached
  the rider.
- With the guardrails removed, the same eval cases drop from
  <!-- claim:summary.accuracy_pct -->100.0% to <!-- claim:ablation.accuracy_pct -->99.1%.
- Live policy agreement on Amazon Bedrock, with and without steering: TODO (E9).

## One thing to know

The vended handler catches exceptions from your `steer_before_tool` and lets the tool proceed. Our
first `Interrupt` passed a dict where the action wanted a string, and the run silently continued.
Test that your handler fires; a buggy handler fails open.

TODO: link to the repo and the sample on the Strands samples fork.
