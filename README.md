# Last Elevator

A Strands agent that watches BART's elevator outage feed for the trips you actually take, applies
BART's own published outage options to your route, and interrupts you only when your trip is broken,
with the workaround already worked out. Entry for the
[AWS Agents for Humans Hackathon](https://agentsforhumans.devpost.com/), Everyday Agents track.

> **Status (Sat Sept 12, 2026, overnight build).** Built and tested offline: knowledge base, BART
> client, outage parser, policy engine, poller, wired agent, evals, the one-page rider app with a
> decisions inbox and replay timeline, the weekly quiet report, rider preferences, and the label
> export and relevance scorer. Every number below was produced by `make evals` or `make replay` on
> the offline mock model provider and is checked by `scripts/verify_claims.py`. What is simulated is
> labeled as simulated here, in the code, and in `docs/reports/day-1.md`. Not built: deployment,
> the live weekend archive, and human relevance labels.

## How it works

1. **Poll.** `src/poller.py` reads BART's elevator advisory every 5 minutes and diffs it against the
   last snapshot in SQLite (new outages, cleared outages).
2. **Parse.** The model proposes a structured parse of BART's free text (`"DELN: Platform - Richmond"`);
   code validates it against the knowledge base and resolves the exact elevator, or refuses.
3. **Decide (code, no model).** `src/policy` matches the outage to the rider's trip (boarding or
   exiting, platform direction from the schedule), pulls BART's documented option for that elevator
   and condition from `kb/`, ranks feasible options in BART's order, computes minutes from the
   schedule, and sets after-dark and last-train flags.
4. **Draft (model, guarded).** A Strands agent with three tools drafts the rider's message. A
   `BeforeToolCall` hook cancels any call naming a station or elevator not in the KB. A steering
   handler (`strands.vended_plugins.steering`) guides `draft_message` back to the policy engine's
   top option. The run ends in a structured `Plan`.
5. **Verify (code).** The Plan's option, minutes, and affected flag are overwritten from the policy
   engine if the model disagreed; the disagreement is recorded, not hidden.

Models propose. Code decides.

## Quickstart (offline, no keys, no network)

```bash
make setup      # .venv with Python 3.12
make verify     # lint, tests, evals, ablation, README claim check, secret scan
make demo-one   # one synthetic outage against one synthetic trip: decision, mechanisms, plan
make replay     # every eval case -> results/replay.md; archived feed -> rider inbox; quiet report
make app        # the rider app on http://127.0.0.1:8000 (register a trip, inbox, replay timeline)
```

Optional credentials are listed by name in `.env.example`. `BART_API_KEY` enables live BART calls;
`AWS_REGION` plus AWS credentials enable Bedrock. Without them nothing touches the network, and
the tests assert that with a socket-blocking fixture.

## Results (mock provider)

| Measure | Value |
| --- | --- |
| Stations in the knowledge base (BART's own accessible-path pages) | <!-- claim:kb_label_distribution.stations -->50|
| Elevators with BART-documented outage options | <!-- claim:kb_label_distribution.elevators_total -->97|
| Documented outage options (each is a labeled eval case) | <!-- claim:kb_label_distribution.options_total -->194|
| Options labeled by the strict rules / the extension tier / left at default | <!-- claim:kb_label_distribution.labeled_by_rule.strict -->136/ <!-- claim:kb_label_distribution.labeled_by_rule.extended -->58/ <!-- claim:kb_label_distribution.labeled_by_rule.default -->0|
| Policy agreement, mock mode (scripted model echoes the KB label; proves plumbing only) | <!-- claim:policy_agreement.agreement_pct -->100.0% on <!-- claim:policy_agreement.cases_run -->194cases |
| Outage parse accuracy, mock mode, with a regex baseline | <!-- claim:outage_parse.accuracy_pct -->100.0% / regex <!-- claim:outage_parse.baselines.regex_accuracy_pct -->100.0% on <!-- claim:outage_parse.cases_run -->10cases |
| All eval cases passed, guardrails on | <!-- claim:summary.cases_passed -->211of <!-- claim:summary.cases_run -->211(<!-- claim:summary.accuracy_pct -->100.0%) |
| All eval cases passed, guardrails removed (ablation) | <!-- claim:ablation.cases_passed -->209of <!-- claim:ablation.cases_run -->211(<!-- claim:ablation.accuracy_pct -->99.1%) |
| Tool calls cancelled by the hook / responses rewritten by steering (harness suites) | <!-- claim:summary.hook_cancellations -->1/ <!-- claim:summary.steering_rewrites -->1|
| Network attempts during the eval run | <!-- claim:summary.network_attempts -->0|
| Demo rider, synthetic weekend archive: outages touching their stations / their trips | <!-- claim:interruptions.rider.outages_touching_your_stations -->3/ <!-- claim:interruptions.rider.outages_touching_your_trips -->3|
| Interruptions the agent sent / what per-station BART alerts would have sent | <!-- claim:interruptions.rider.interruptions_sent -->4/ <!-- claim:interruptions.rider.bart_style_station_alerts -->6|
| Relevance rows exported for two human labelers / rows labeled so far | <!-- claim:relevance.rows_total -->8/ <!-- claim:relevance.rows_labeled_by_both -->0|

The interruption numbers come from a synthetic four-snapshot archive replayed through the pipeline
(`fixtures/bart/archive_synthetic.json`), not from a real weekend; the relevance score is unfilled
until two people label the exported rows. The policy-agreement number is not a model-quality number yet: the scripted model returns the
label. The live-mode run (credentials, capped at 200 model calls) reports the real number and has
not been run. Stations with accessible-pathway prose on BART's page: <!-- claim:kb_label_distribution.stations_with_pathways -->1; the other
<!-- claim:kb_label_distribution.stations_pathways_unknown -->49are recorded as `unknown`, not invented.

## What is simulated or unverified

- **The model.** Every eval, demo, and replay runs on scripted turns (`fixtures/model`, inline
  `mock_turns`). No Bedrock call has been made.
- **BART API responses.** `fixtures/bart` are BART's documented samples (verbatim or with recorded
  repairs) plus synthetic snapshots and schedules, each labeled. No live call has been made; the
  poller and client run live only with `BART_API_KEY`.
- **Minutes.** Backtracking minutes come from synthetic schedule fixtures and are labeled as such
  in every plan. Distances in BART's text are converted at 3 mph, an assumption.
- **BART's ranked option order** (alternate elevator, backtracking, transit, Mitigation Trip,
  Mitigation Shuttle) is recorded as unverified in `kb/policy.json`: the page that stated it
  returned HTTP 403 during the build. The per-station options are BART's own text.
- **Option labels** are derived from BART's text by fixed rules (`kb/labels.py`), with the
  extension tier reviewable in `results/kb_label_distribution.json`.

## Layout

| Path | What |
| --- | --- |
| `kb/` | Station knowledge base: raw page captures, `stations/<ABBR>.json`, index, labels, build |
| `src/bart/` | BART API client (JSON mode), fixtures by default |
| `src/policy/` | Trip matcher, option ranking, schedule minutes, sunset |
| `src/agent/` | Tools, hook, steering, `Plan` schema, mock model, run orchestration |
| `src/poller.py` | Feed poller with SQLite snapshot diff and optional raw archive |
| `src/app/` | Rider app: store, archived-feed replay into the inbox, one-page UI |
| `src/report.py` | Weekly quiet report per rider |
| `evals/` | Case suites, runner, policy-agreement case generator |
| `results/` | Everything `make evals` and `make replay` produce |
| `tests/` | Offline tests; `tests/test_strands_mechanics.py` is the standing proof of the three mechanisms |

## Documents

- `JUDGING.md`: the 60-second route.
- `docs/reports/day-1.md`: proven by command, claimed but not proven, deliberately not built.
- `docs/strategy.md`, `TODO.md`, `CLAUDE.md`: pitch, plan, and the standard this repo is built to.
- `SUBMISSION.md`: Devpost checklist.

## License

Apache-2.0. See `LICENSE`.
