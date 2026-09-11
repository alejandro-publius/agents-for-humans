# CLAUDE.md

This repo is a hackathon entry for the AWS Agents for Humans hackathon (deadline Mon Sept 14, 2026, 5:00pm PT). Working title Last Elevator. The build standard is the one below, and it matters more than speed.

## The standard
- Nothing is done until its acceptance command has run in this session and the output is visible. "Should work" is not done.
- Every number that appears in README.md is produced by `make evals` and checked by `scripts/verify_claims.py`. Never type a number into README by hand.
- Models propose. Code decides. The Strands agent may parse text, rank feasible options, and draft messages. It may not decide whether a trip is affected, compute minutes, or assert a station that is not in `kb/`. Those are code paths with tests.
- Honesty over polish. If a thing is simulated, say so in the code, the README, and `docs/reports/`.

## Environment
- Python 3.12, `make setup` creates `.venv`.
- Strands Agents SDK. `pip install strands-agents strands-agents-tools`. The SDK lives in the harness-sdk monorepo as of 2026. Before using any class or hook name, inspect the installed package. Do not trust tutorials or memory for API names.
- No credentials by default. `AWS_REGION` plus AWS credentials enable Bedrock. `BART_API_KEY` enables live BART calls. Absent those, everything runs on `fixtures/` and the mock provider at $0, and CI asserts that with a network-blocking test fixture.
- Never write secrets to disk. `.env.example` lists variable names only.

## Git
- Branch `overnight`. Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). One TODO item per commit. Commit only when `make verify` is green.
- Do not force-push, rebase, or touch `main`.

## Things you must not do tonight
- Deploy to AWS, create AWS resources, or run `agentcore` commands.
- Publish anything, open issues or PRs on other repos, or send email.
- Spend money. Bedrock is off unless credentials are present, and even then keep any single eval run under 200 model calls.
- Scrape bart.gov faster than one request per second, or scrape anything other than the accessibility pages listed in TODO.md.
- Invent BART station facts. If a pathway page is missing or unparseable, record `unknown` and note it in the day report.

## When stuck
Write the blocker and what you tried in `docs/reports/day-1.md` under "claimed but not proven," commit, and move to the next TODO item. Do not spend more than 30 minutes on any single item.
