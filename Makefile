# Last Elevator. Every target runs offline unless credentials are present (see .env.example).
.DEFAULT_GOAL := help
SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
UV    := $(shell command -v uv 2>/dev/null)
ABLATE ?= 0

.PHONY: help setup lint test evals evals-ablate evals-no-steering results render-claims verify-claims secret-scan verify replay poll demo-one app inbox-replay report labels relevance archive quota bedrock-smoke eval-live red-team a11y trace mcp-test clean

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## create .venv (Python 3.12) and install the project with dev extras; uv if present, else venv + pip
ifdef UV
	uv sync --all-extras
else
	test -d $(VENV) || python3.12 -m venv $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -e ".[dev]"
endif
	@$(PY) -c "import sys; assert sys.version_info >= (3, 12), sys.version; print('python', sys.version.split()[0])"

lint: ## ruff check + format check
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

test: ## unit tests, fully offline
	$(PY) -m pytest -q

evals: ## run eval cases on the mock provider and write results/*.json; ABLATE=1 disables hook + steering
	$(PY) evals/run.py $(if $(filter 1,$(ABLATE)),--ablate,)

evals-ablate: ## same cases with hook + steering disabled -> results/ablation.json
	$(PY) evals/run.py --ablate

evals-no-steering: ## policy_agreement ablation on the mock provider: no steering, no get_station_facts
	$(PY) evals/run.py --no-steering

demo-one: ## one synthetic outage against one synthetic trip on the mock provider; ARGS=--after-dark shows the pause
	$(PY) scripts/demo_one.py $(ARGS)

poll: ## one poll of the elevator feed into data/outages.sqlite; FIXTURE=path runs offline, else needs BART_API_KEY
	$(PY) -m src.poller --once $(if $(FIXTURE),--fixture $(FIXTURE),)

replay: inbox-replay ## offline: every eval case -> results/replay.md, the archived feed -> inbox, then the quiet report
	$(PY) scripts/replay.py
	$(PY) -m src.report --rider demo
	$(PY) scripts/export_labels.py
	$(PY) -m evals.relevance

labels: ## export evals/labels/relevance.csv from the inbox (keeps existing human labels)
	$(PY) scripts/export_labels.py

relevance: ## score agent interruptions against the two label columns -> results/relevance.json
	$(PY) -m evals.relevance

archive: ## live: poll every 5 min with BART_API_KEY into data/archive/ (own db, never touched by make replay)
	$(PY) -m src.poller --interval 300 --archive-dir data/archive --db data/archive/outages.sqlite --env-file .env

bedrock-smoke: ## one Converse call to the eval model in AWS_REGION; prints the reply; creates nothing
	$(PY) scripts/bedrock_smoke.py

eval-live: ## exactly once: policy_agreement on Bedrock, enforced then --no-steering, hard cap 200 calls each
	$(PY) evals/run.py --provider bedrock --suite policy_agreement --max-model-calls 200 --env-file .env
	$(PY) evals/run.py --provider bedrock --no-steering --max-model-calls 200 --env-file .env

quota: ## read-only: print the Amazon Bedrock AgentCore Runtime quotas for this account/region (needs AWS creds)
	$(PY) scripts/agentcore_quota.py

report: ## weekly quiet report for one rider -> results/interruptions.json (RIDER=demo)
	$(PY) -m src.report --rider $(or $(RIDER),demo)

inbox-replay: ## offline: replay the archived feed into data/riders.sqlite inbox (seeds the demo rider)
	$(PY) -m src.app.replay --reset --seed-demo

app: ## serve the rider app on http://127.0.0.1:8000 (reads data/*.sqlite; no model, no network)
	$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000

results: ## print results/summary.json
	@cat results/summary.json

render-claims: ## copy current results/*.json values into the README claim markers (never type numbers)
	$(PY) scripts/render_claims.py

verify-claims: ## every number in README.md marked <!-- claim:key --> must match results/*.json
	$(PY) scripts/verify_claims.py

secret-scan: ## regex scan of every tracked file for keys and tokens
	$(PY) scripts/secret_scan.py

mcp-test: ## a Strands agent over MCP stdio gets the same plan as make demo-one; unknown stations are refused
	$(PY) -m pytest tests/test_mcp.py -q

trace: ## capture make demo-one spans to docs/traces/demo_one.jsonl and render docs/traces/demo_one.txt
	$(PY) scripts/demo_one.py --trace docs/traces/demo_one.jsonl > /dev/null
	$(PY) scripts/render_trace.py docs/traces/demo_one.jsonl docs/traces/demo_one.txt

a11y: ## axe-core audit of the served rider app (Playwright Chromium) -> results/axe.json; exits 1 on violations
	$(PY) scripts/a11y.py

red-team: ## adversarial scripted model vs the full agent -> results/red_team.json (expect all zeros reach the rider)
	$(PY) scripts/red_team.py

verify: lint test evals evals-ablate evals-no-steering red-team verify-claims secret-scan ## everything CI runs, no secrets needed
	@echo "verify: OK"

clean: ## remove the virtualenv and caches
	rm -rf $(VENV) .pytest_cache .ruff_cache
