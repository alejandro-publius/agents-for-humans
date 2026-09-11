# Judging route (about 60 seconds, no keys, no network after install)

```bash
git clone https://github.com/alejandro-publius/agents-for-humans.git last-elevator
cd last-elevator
make setup      # creates .venv with Python 3.12 (uses uv if installed, else venv + pip)
make replay     # runs every case through the agent offline and writes results/replay.md
open results/replay.md   # or: less results/replay.md
```

## What you are looking at

`results/replay.md` is a transcript of the real Strands agent loop, one section per case: the
prompt, each tool call, the hook cancelling any call that names a station outside the knowledge
base, the steering handler rewriting a response that recommends the wrong option, and the final
structured `Plan`.

## What is simulated

The model. Every replay and eval runs on a scripted mock provider (`fixtures/model/*.json`) so the
route is free, offline, and deterministic. To run against Amazon Bedrock, set `AWS_REGION` and
credentials (names in `.env.example`) and pass `--provider bedrock` to `evals/run.py`.

## Where the numbers come from

```bash
make verify     # lint, tests (network blocked), evals, ablation, README claim check, secret scan
```

Every number in `README.md` is a `<!-- claim:key -->` that `scripts/verify_claims.py` checks
against `results/*.json`. If a number is in the README, it was produced by `make evals`.

## Map

| Question | Look at |
| --- | --- |
| How does the agent decide? | `src/agent/core.py`, `src/agent/steering.py`, `src/agent/hooks.py` |
| What does the model return? | `src/agent/schema.py` (`Plan`) |
| What did it do on each case? | `results/replay.md` |
| What do the guardrails buy? | `results/summary.json` vs `results/ablation.json` |
| What was built, proven, and skipped tonight? | `docs/reports/day-1.md` |
