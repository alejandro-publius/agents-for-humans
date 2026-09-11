# Day 1 report. Overnight build, Fri Sept 11, 2026

Branch `overnight`. Everything below ran on the offline mock model provider with the network
blocked. No AWS resources, no deployments, no posts, no spend.

## Proven by a command with observed output

Each line names the command that ran in this session and what it printed.

- **A1 repo skeleton.** `make setup && make lint && make test` exited 0: `python 3.12.0`, `All checks passed!`, `1 passed`.
- **A2 mock provider.** `pytest tests/test_mock_provider.py -q` printed `9 passed`. The agent completed one turn on `fixtures/model/one_turn_text.json` with the socket-blocking fixture recording `attempts == []`; the same fixture is proven armed by a test that expects `socket.create_connection` to raise.
- **A3 hook, steering, structured output.** `pytest tests/test_hooks.py tests/test_steering.py tests/test_structured_output.py -q` printed `10 passed`. Captured output showed the hook cancelling `get_station_facts(station="ZZZZ")` with `CANCELLED by ArgumentValidatorHook: station='ZZZZ' is not a known station`, the steering handler rewriting a Mitigation Shuttle draft to `Backtracking is the first feasible option under BART's published outage order…`, and a validated `Plan(option='alternate elevator', added_minutes=3, …)`. Ablation tests show both mechanisms are what cause those outcomes.
- **A4 evals harness.** `make evals` printed `full total 7/7 passed, network_attempts=0` and wrote `results/summary.json` with `cases_run: 7`. A temporary case without a `label` made `make evals` exit 2 (`make: *** [evals] Error 2`). Strands Evals (`strands-agents-evals 1.2.0`) installed in about one second and is used for scoring (`Experiment` + deterministic `Equals`), so no pytest fallback was needed.
- **A5 ablation.** `make evals ABLATE=1` printed `ABLATED total 5/7 passed` and wrote `results/ablation.json`; a field-by-field diff against `summary.json` listed 20 differing fields (for example `hook_cancellations 1 -> 0`, `steering_rewrites 1 -> 0`, `accuracy_pct 100.0 -> 71.4`). `tests/test_ablation.py` locks this in.
- **A6 claim verification.** `make verify` printed `verify_claims: 12 claim(s) match results/` and `verify: OK`. After changing the README's `cases_passed` claim from 7 to 9, `make verify` printed `MISMATCH summary.cases_passed README=9 results=7` and `make: *** [verify-claims] Error 1`. README restored.
- **A7 CI and secret scan.** `python -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))"` parsed the workflow (one job, four steps). `make verify` printed `secret_scan: 50 tracked files clean`; `pytest tests/test_secret_scan.py -q` printed `4 passed` after planting each key shape.
- **A8 judging route.** From a fresh `git clone -b overnight` into `/tmp`: clone 1s, `make setup` 0s (uv cache was warm; see below), `make replay` 4s, total 5s. `results/replay.md` opened and showed the cancelled tool call for case `harness_hook / unknown_station_is_cancelled`.

## Claimed but not proven

- **`make setup` on a cold machine.** The 0s figure came from a warm uv cache. A first-time install downloads Python 3.12 and about 60 packages; expect tens of seconds, not zero.
- **CI on GitHub.** The workflow file parses and `make verify` passes locally, but the `overnight` branch has not been pushed, so no Actions run exists yet.
- **Bedrock provider path.** `evals/run.py --provider bedrock` is written but untested: no credentials were present, by design.
- **The numbers mean harness correctness, not model quality.** Every eval and replay uses scripted model turns. A 100% pass rate here says the hook, steering handler, and schema behave; it says nothing about how a real model would plan. Real outage numbers are Block B and C work.

## Deliberately not built

- Anything that deploys, creates AWS resources, runs `agentcore`, sends email or SMS, or spends money. Deployment is a human decision in the morning (TODO C5).
- gitleaks. A regex scanner (`scripts/secret_scan.py`) covers the key shapes we could plausibly leak, with tests; the CI job runs it with no secrets configured.
- The rider app, weekly quiet report, preferences memory, and live archive (Block C). None should start overnight.
- Live BART calls. Without `BART_API_KEY` the client reads `fixtures/bart/` (Block B).
