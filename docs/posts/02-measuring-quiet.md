# Agents for Humans: measuring an agent by how rarely it interrupts, with Strands Evals

_Draft for builder.aws.com. Numbers are claim markers from `results/`; TODO marks the live numbers._

Most agent demos are judged by what they say. A background agent should be judged by what it does
not say. Last Elevator watches BART's elevator feed for a rider's registered trips and speaks only
when a trip is broken. The metric that matters is interruptions per rider-week, next to what the
operator's own per-station alerts would have sent.

## The harness

Every eval runs through `strands_evals.Experiment` with the deterministic `Equals` evaluator on the
offline mock provider, so it is free and reproducible. `make evals` writes `results/*.json`,
`make render-claims` copies numbers into the README, and `scripts/verify_claims.py` fails CI if any
README number drifts from results.

## The numbers so far

- Policy agreement: one case per (station, elevator, condition) from BART's pages,
  <!-- claim:policy_agreement.enforced.cases_run -->194 cases; mock mode proves the plumbing at
  <!-- claim:policy_agreement.enforced.agreement_pct -->100.0%. Live Bedrock numbers: TODO (E9).
- Synthetic weekend replay: <!-- claim:interruptions.rider.interruptions_sent -->4 interruptions
  where per-station alerts would have sent
  <!-- claim:interruptions.rider.bart_style_station_alerts -->6; live weekend: TODO (archive).
- Relevance: <!-- claim:relevance.rows_total -->8 decision rows exported for two independent human
  labelers; precision, recall and Cohen's kappa are null until the labels exist.

## Honesty envelope

The scripted model returns the label, so the mock numbers measure the harness, not the model. The
interruption ratio comes from a synthetic archive that spans fifteen minutes. Both are labeled as
such in the repo and will be replaced by the live numbers. TODO: update after the live runs.
