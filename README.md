# Last Elevator

A Strands agent that watches BART's elevator outage feed for the trips you actually take, applies
BART's own published outage rules to your route, and interrupts you only when your trip is broken,
with the workaround and the Mitigation Trip request already drafted.

Entry for the [AWS Agents for Humans Hackathon](https://agentsforhumans.devpost.com/), Everyday Agents track.

> **Status: overnight build in progress.** Every number in this README is produced by `make evals`
> and checked by `scripts/verify_claims.py`; none are typed by hand. What is simulated is labeled
> as simulated here, in the code, and in `docs/reports/`.

## Quickstart (offline, no keys)

```bash
make setup     # .venv with Python 3.12
make verify    # lint + tests, runs on the mock model provider at $0
```

Optional credentials are listed by name in `.env.example`. Without them nothing touches the network.

## Results so far

Produced by `make evals` on the offline mock provider and checked by `scripts/verify_claims.py`.
These numbers measure the harness (hook, steering handler, schema), not model quality; the model is
scripted. Real outage numbers arrive with Block B.

| Measure | With guardrails | Guardrails removed (ablation) |
| --- | --- | --- |
| Harness cases run | <!-- claim:summary.cases_run -->211| <!-- claim:ablation.cases_run -->211|
| Cases passed | <!-- claim:summary.cases_passed -->211| <!-- claim:ablation.cases_passed -->209|
| Pass rate | <!-- claim:summary.accuracy_pct -->100.0% | <!-- claim:ablation.accuracy_pct -->99.1% |
| Tool calls cancelled by the hook | <!-- claim:summary.hook_cancellations -->1| <!-- claim:ablation.hook_cancellations -->0|
| Responses rewritten by steering | <!-- claim:summary.steering_rewrites -->1| <!-- claim:ablation.steering_rewrites -->0|
| Network attempts during the run | <!-- claim:summary.network_attempts -->0| <!-- claim:ablation.network_attempts -->0|

## Documents

- `TODO.md`: the build list and acceptance commands.
- `CLAUDE.md`: the standard this repo is built to.
- `docs/strategy.md`: pitch, data sources, architecture, proof set, honesty envelope.
- `SUBMISSION.md`: Devpost checklist.

## License

Apache-2.0. See `LICENSE`.
