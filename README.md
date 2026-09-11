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

## Documents

- `TODO.md`: the build list and acceptance commands.
- `CLAUDE.md`: the standard this repo is built to.
- `docs/strategy.md`: pitch, data sources, architecture, proof set, honesty envelope.
- `SUBMISSION.md`: Devpost checklist.

## License

Apache-2.0. See `LICENSE`.
