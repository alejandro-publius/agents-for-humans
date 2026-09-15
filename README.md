# Last Elevator

A Strands agent that watches BART's elevator outage feed for the trips you actually take, applies
BART's own published outage options to your route, and interrupts you only when your trip is broken,
with the workaround already worked out. Entry for the
[AWS Agents for Humans Hackathon](https://agentsforhumans.devpost.com/), Everyday Agents track.

> **Status (Sat Sept 12, 2026).** Built and tested offline: knowledge base, BART client, outage
> parser, policy engine, poller, wired agent with real Strands Interrupts for rider decisions, evals,
> a red team, the one-page rider app (0 axe-core violations) with a decisions inbox and replay
> timeline, the weekly quiet report, rider preferences, label export and relevance scorer, file
> tracing with the guardrail spans, an MCP server, a reusable example, and a dataset exporter.
> Every number in this README, in `docs/devpost.md`, in `docs/VIDEO.md` and in `docs/posts/` is a
> claim rendered from `results/` by `make render-claims` and checked by `scripts/verify_claims.py`;
> what is not measured yet is marked TODO. Not done: the live Bedrock evals (E9, waiting for
> credentials), the live weekend archive and dataset, human relevance labels, and deployment.

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
| Options labeled by a reviewer-decided phrase rule / left at default | <!-- claim:kb_label_distribution.labeled_by_rule.phrase -->194/ <!-- claim:kb_label_distribution.labeled_by_rule.default -->0|
| Labels: alternate_elevator / backtracking / transit (frozen as `kb-labels-v1`) | <!-- claim:kb_label_distribution.counts.alternate_elevator -->55/ <!-- claim:kb_label_distribution.counts.backtracking -->53/ <!-- claim:kb_label_distribution.counts.transit -->86|
| Policy agreement, enforced (steering on), mock mode: no live run yet | <!-- claim:policy_agreement.enforced.agreement_pct -->100.0% on <!-- claim:policy_agreement.enforced.cases_run -->194 cases |
| Policy agreement, no steering and no get_station_facts (unaided), mock mode: no live run yet | <!-- claim:policy_agreement.no_steering.agreement_pct -->100.0% on <!-- claim:policy_agreement.no_steering.cases_run -->194 cases |
| Outage parse accuracy, mock mode, with a regex baseline | <!-- claim:outage_parse.accuracy_pct -->100.0% / regex <!-- claim:outage_parse.baselines.regex_accuracy_pct -->100.0% on <!-- claim:outage_parse.cases_run -->10 cases |
| All eval cases passed, guardrails on | <!-- claim:summary.cases_passed -->211 of <!-- claim:summary.cases_run -->211 (<!-- claim:summary.accuracy_pct -->100.0%) |
| All eval cases passed, guardrails removed (ablation) | <!-- claim:ablation.cases_passed -->209 of <!-- claim:ablation.cases_run -->211 (<!-- claim:ablation.accuracy_pct -->99.1%) |
| Tool calls cancelled by the hook / responses rewritten by steering (harness suites) | <!-- claim:summary.hook_cancellations -->1/ <!-- claim:summary.steering_rewrites -->1|
| Network attempts during the eval run | <!-- claim:summary.network_attempts -->0|
| Demo rider, synthetic weekend archive: outages touching their stations / their trips | <!-- claim:interruptions.rider.outages_touching_your_stations -->3/ <!-- claim:interruptions.rider.outages_touching_your_trips -->3|
| Interruptions the agent sent / what per-station BART alerts would have sent | <!-- claim:interruptions.rider.interruptions_sent -->4/ <!-- claim:interruptions.rider.bart_style_station_alerts -->6|
| Relevance rows exported for two human labelers / rows labeled so far | <!-- claim:relevance.rows_total -->8/ <!-- claim:relevance.rows_labeled_by_both -->0|
| Red team (fake stations half obvious and half plausible, wrong options, minutes invented in the field and in the prose): reached the rider | <!-- claim:red_team.reached_rider.hallucinated_stations -->0 stations / <!-- claim:red_team.reached_rider.wrong_options -->0 options / <!-- claim:red_team.reached_rider.minutes_not_from_policy -->0 minutes, over <!-- claim:red_team.runs -->30 runs |
| Quiet metric, synthetic replay: interruptions / decisions / days covered | <!-- claim:quiet.synthetic_replay.interruptions -->4/ <!-- claim:quiet.synthetic_replay.decisions -->8/ <!-- claim:quiet.synthetic_replay.days_covered -->0.0104|
| Rider app accessibility, axe-core violations on the served page (`make a11y`) | <!-- claim:axe.violations -->0 violations, <!-- claim:axe.passes -->35 rules passed |

The interruption numbers come from a synthetic four-snapshot archive replayed through the pipeline
(`fixtures/bart/archive_synthetic.json`), not from a real weekend; the relevance score is unfilled
until two people label the exported rows. The two policy-agreement numbers are not model-quality numbers yet: the scripted model returns
the label, so both prove plumbing. The live run (Bedrock, frozen `kb-labels-v1` labels, hard cap of
200 model calls per variant, exactly once) has not happened because no AWS credentials were
present; when it runs, its two numbers replace these. Stations with accessible-pathway prose on BART's page: <!-- claim:kb_label_distribution.stations_with_pathways -->1; the other
<!-- claim:kb_label_distribution.stations_pathways_unknown -->49 are recorded as `unknown`, not invented.

## What is simulated or unverified

- **The model.** Every eval, demo, and replay runs on scripted turns (`fixtures/model`, inline
  `mock_turns`). No Bedrock call has been made.
- **BART API responses.** `fixtures/bart` are BART's documented samples (verbatim or with recorded
  repairs) plus synthetic snapshots and schedules, each labeled. No live call has been made; the
  poller and client run live only with `BART_API_KEY`.
- **Minutes.** Backtracking minutes come from synthetic schedule fixtures and are labeled as such
  in every plan. Distances in BART's text are converted at 3 mph, an assumption.
- **BART's ranked option order** (alternate elevator when one exists, then backtracking, transit,
  Mitigation Trip, Mitigation Shuttle) was verified by a person against the live page
  https://www.bart.gov/guide/accessibility/elevators on Fri Sept 11, 2026, and is recorded in
  `kb/policy.json`. The automated capture saw HTTP 403 for that page because BART's WAF blocks this
  laptop's IP. The per-station options are BART's own text.
- **Option labels** are derived from BART's text by fixed phrase rules (`kb/labels.py`), every one
  decided by a reviewer against the actual texts and frozen as `kb-labels-v1`. alternate_elevator
  means an alternate accessible path at the same station, including ramps, lifts and tunnels.
  `results/kb_label_distribution.json` lists the counts and any text left at the default (none).

## Guarantees and the evidence (Block E)

| Guarantee | Mechanism | Evidence |
| --- | --- | --- |
| A rider decision (after dark, last train) pauses the run instead of guessing | Strands steering `Interrupt`, decision card, resume with the answer remembered in session state | `tests/test_strands_mechanics.py`, `make demo-one ARGS=--after-dark`, `POST /decisions/{id}` |
| Nothing the model invents reaches the rider | `BeforeToolCall` hook, steering `Guide`, `Plan` schema, code verification with a station-code scrub | `make red-team`: <!-- claim:red_team.reached_rider.hallucinated_stations -->0/ <!-- claim:red_team.reached_rider.wrong_options -->0/ <!-- claim:red_team.reached_rider.minutes_not_from_policy -->0 reached the rider over <!-- claim:red_team.runs -->30 runs |
| The agent is measured by how rarely it interrupts | `results/quiet.json`, `make report` opens with days, interruptions, decisions | <!-- claim:quiet.synthetic_replay.interruptions -->4 interruptions over <!-- claim:quiet.synthetic_replay.decisions -->8 decisions (synthetic); archive: TODO |
| The rider app is accessible | axe-core via Playwright Chromium, in CI | <!-- claim:axe.violations -->0 violations |
| Every guardrail decision is visible in traces | OpenTelemetry spans to a file, `hook.cancel_tool` and `steering.guide` events; `AGENTCORE_OBSERVABILITY=1` switches to OTLP | `docs/traces/demo_one.txt` |
| The pattern is reusable | Standalone example, scripted model, no BART data | `examples/compliance_steering.py`; samples fork branch `compliance-steering-sample` |
| The grounding tools work over MCP with the same guarantees | `MCPServer` over stdio, KB checks inside the tools | `make mcp-test` |
| The outage archive becomes a public dataset | `make dataset` with BART attribution and a README line | TODO: needs an hour of live archive |

## Still TODO

- Live policy-agreement evals on Amazon Bedrock (Sonnet profile and Amazon Nova Lite, enforced and
  no-steering, 200 calls each): waiting for credentials ("aws ready").
- Live weekend archive (`make archive` with `BART_API_KEY`), the dataset export, the real
  interruption ratio, and two human labelers for `evals/labels/relevance.csv`.
- Deployment (C5), the public URL, the video, and the architecture diagram export.

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

MIT. See `LICENSE`.
