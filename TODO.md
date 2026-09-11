# TODO.md. Overnight build, Fri Sept 11, 2026

Rules for this list. Work top to bottom. An item is done only when its acceptance command has been run and its output is in the transcript. Each finished item gets its own commit on branch `overnight` with a conventional-commit message. Do not skip to Block B before every Block A item is checked. Never mark an item done that you did not watch pass.

Constraints that hold all night.
- Python 3.12. `pip install strands-agents strands-agents-tools`. Verify every Strands import against the installed package (the SDK moved to the harness-sdk monorepo in 2026 and older tutorials are wrong). Read `python -c "import strands, inspect; print(strands.__file__)"` and the package's own docstrings before using an API.
- No AWS or Bedrock call unless `AWS_REGION` and credentials are present in the environment. Without them, every test and eval runs on the offline mock model provider at $0.
- No BART network call unless `BART_API_KEY` is set. Without it, use `fixtures/bart/*.json`.
- No secrets in the repo. `.env.example` only. The secret scan in `make verify` must stay green.
- Do not deploy anything, post anything, or spend money. Deployment is a human decision in the morning.
- If an item cannot be completed, write why in `docs/reports/day-1.md` under "claimed but not proven" and move on. Do not loop on it.

## Block A. Harness (idea-agnostic)

- [x] A1. Repo skeleton. `pyproject.toml`, `Makefile` with targets `setup lint test evals results verify`, `LICENSE` (Apache-2.0), `README.md` stub, `.gitignore`, `.env.example`, `docs/`, `evals/`, `results/`, `scripts/`, `src/agent/`.
      Accept. `make setup && make lint && make test` exits 0 with at least one passing test.
- [x] A2. Offline mock model provider for Strands so the agent runs with no credentials. Scripted responses loaded from `fixtures/model/*.json`.
      Accept. `pytest tests/test_mock_provider.py -q` passes and shows the agent completing one turn with zero network calls (assert via a socket-blocking fixture).
- [x] A3. Agent skeleton in `src/agent/`. One `strands.Agent` with three placeholder tools, a `BeforeToolCall` hook that cancels any call whose arguments fail a validator, a steering handler that rewrites a response when a policy check fails, and a structured-output schema for the final plan. Each mechanism has its own unit test that proves it fires.
      Accept. `pytest tests/test_hooks.py tests/test_steering.py tests/test_structured_output.py -q` passes, and the transcript shows the hook cancelling a bad call and the steering handler rewriting a bad response.
- [x] A4. Evals harness. `evals/run.py` loads cases from `evals/cases/*.json`, runs them through the agent (mock provider by default), writes `results/*.json` with counts, and exits non-zero if any case is missing a label. Try `strands-agents-evals` from https://github.com/strands-agents/evals first; if it cannot be installed in ten minutes, implement a minimal pytest-based runner and note the fallback in `docs/reports/day-1.md`.
      Accept. `make evals` writes `results/summary.json` with `cases_run > 0`.
- [x] A5. Ablation switch. `make evals ABLATE=1` runs the same cases with the hook and steering handler disabled and writes `results/ablation.json`.
      Accept. Both files exist and differ in at least one field.
- [x] A6. `scripts/verify_claims.py`. Reads every number in `README.md` marked with `<!-- claim:key -->` and compares it to `results/*.json`. Fails on mismatch or on a claim with no result.
      Accept. `make verify` exits 0 with one real claim in the README, and exits 1 when a README number is deliberately changed (show both runs).
- [x] A7. CI. `.github/workflows/ci.yml` runs `make verify` on push with no secrets. Secret scan step using gitleaks or a regex script.
      Accept. Workflow file lints (`python -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))"`) and `make verify` passes locally.
- [x] A8. `JUDGING.md` with a 60-second route: clone, `make setup`, `make replay`, open one output file. `make replay` must work offline.
      Accept. Run the route from a fresh clone into `/tmp` and paste the timing.
- [x] A9. `docs/reports/day-1.md` with three sections, proven by a command with observed output, claimed but not proven, deliberately not built.
      Accept. File exists and every "proven" line names a command run in this session.

## Block B. Last Elevator (only after Block A is fully checked)

- [x] B1. Station knowledge base. Scrape https://www.bart.gov/guide/accessibility/elevators and the linked accessible-pathway pages and station-specific outage-option pages into `kb/stations/<ABBR>.json` with fields `name, abbr, elevators[], pathways[], documented_outage_options[], source_url, scraped_at`. Rate limit one request per second. If a page is a PDF, extract text with pdfplumber. Commit the JSON so nothing later depends on live scraping.
      Accept. `python -m kb.build` reports the number of stations with pathways and the number with documented outage options, and `pytest tests/test_kb.py` checks every file has a source URL and timestamp.
- [ ] B2. BART client. `src/bart/client.py` for `bsa.aspx?cmd=elev`, `cmd=bsa`, `etd.aspx`, `sched.aspx?cmd=depart`, `stn.aspx`, JSON mode. Live only with `BART_API_KEY`; otherwise reads `fixtures/bart/`. Record three real responses into fixtures if the key is present, else author realistic fixtures from the documented samples at https://api.bart.gov/docs/bsa/elev.aspx and mark them synthetic.
      Accept. `pytest tests/test_bart_client.py -q` passes offline.
- [ ] B3. Outage parser. Turn the free-text elevator description (for example the documented sample "DELN: Platform - Richmond") into `{station_abbr, level_from, level_to, platform_label}` using the model with structured output, validated against the KB by code. Ten labeled examples in `evals/cases/outage_parse.json`.
      Accept. `make evals` shows `outage_parse` accuracy on the ten cases.
- [ ] B4. Trip matcher and policy engine, pure code. Given a rider trip `{origin, dest, days, window, needs}` and an outage, decide affected or not, then rank options in BART's published order: alternate elevator, backtracking, transit, Mitigation Trip, Mitigation Shuttle. Compute added minutes from `sched.aspx` fixtures. Flags for after dark (sunset computed locally) and last train.
      Accept. `pytest tests/test_policy.py -q` covers the boarding and exiting examples from the BART page (San Leandro to SF, and SF to El Cerrito Plaza via Del Norte) and passes.
- [ ] B5. Poller. `src/poller.py` polls every 5 minutes, diffs against the last snapshot, writes new or changed outages to `data/outages.sqlite`. Runs live only with the key.
      Accept. `python -m src.poller --once --fixture fixtures/bart/elev_sample.json` inserts rows and a second run inserts none.
- [ ] B6. Wire the agent. Replace the placeholder tools with `get_station_facts`, `plan_alternatives`, `draft_message`. Steering handler enforces BART's option order. Hook cancels any tool call naming a station not in the KB.
      Accept. `make demo-one` runs a synthetic outage against a synthetic trip on the mock provider and prints a structured plan whose option matches the policy engine's top feasible option.
- [ ] B7. Policy-agreement eval. One case per station with documented outage options. The label is BART's own text. Report agreement in `results/policy_agreement.json`.
      Accept. `make evals` reports the agreement number, whatever it is. Do not tune labels to pass.
- [ ] B8. Update `docs/reports/day-1.md` and the README claim table with the numbers produced tonight, then `make verify`.
      Accept. `make verify` exits 0 and `git status` is clean on branch `overnight`.

## Block C. Grand-prize surface (Friday daytime, after a human reviews Blocks A and B)

These are the items that move the entry from "proof of concept" to "complete product" on the Design criterion. None of them should start overnight.

- [ ] C1. Rider app. One page served by FastAPI. Register a trip (origin, destination, days, window, needs), an inbox of every decision the agent made with the reasoning and the BART option ranking shown, and a replay timeline a judge can scrub through the weekend's real outages.
      Accept. `make app` serves on localhost, a registered trip appears in `data/riders.sqlite`, and `make replay` populates the inbox from the archived feed with no network.
- [ ] C2. Weekly quiet report. From `data/outages.sqlite`, generate "N outages touched your stations, M touched your trips, K interruptions sent" per rider, plus the BART-style alert count for comparison.
      Accept. `python -m src.report --rider demo` prints the four numbers and writes `results/interruptions.json`.
- [ ] C3. Rider preferences memory. A `preferences` object per rider (prefers backtracking to buses, never travels after dark, needs the larger elevator) that changes option ranking. Store in AgentCore Memory when credentials are present, local JSON otherwise, behind one interface.
      Accept. `pytest tests/test_preferences.py` shows the same outage producing two different top options for two riders.
- [ ] C4. Live archive and labels. With `BART_API_KEY`, run the poller continuously through Sunday. Export `evals/labels/relevance.csv` with one row per outage per demo trip and two label columns for two independent labelers. Report agreement.
      Accept. `results/relevance.json` reports precision, recall, and inter-labeler agreement.
- [ ] C5. Deploy. Human decision first. AgentCore Runtime if the quota allows, otherwise Lambda plus EventBridge for the poller and a public URL for the app. Record the ARN or URL in README.
      Accept. Public URL loads from a phone, and a forced outage produces an inbox entry.
