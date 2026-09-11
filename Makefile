# Last Elevator. Every target runs offline unless credentials are present (see .env.example).
.DEFAULT_GOAL := help
SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
UV    := $(shell command -v uv 2>/dev/null)
ABLATE ?= 0

.PHONY: help setup lint test evals evals-ablate results render-claims verify-claims secret-scan verify replay poll demo-one app inbox-replay report clean

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

demo-one: ## one synthetic outage against one synthetic trip on the mock provider; prints decision, mechanisms, plan
	$(PY) scripts/demo_one.py

poll: ## one poll of the elevator feed into data/outages.sqlite; FIXTURE=path runs offline, else needs BART_API_KEY
	$(PY) -m src.poller --once $(if $(FIXTURE),--fixture $(FIXTURE),)

replay: inbox-replay ## offline: every eval case -> results/replay.md, the archived feed -> inbox, then the quiet report
	$(PY) scripts/replay.py
	$(PY) -m src.report --rider demo

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

verify: lint test evals evals-ablate verify-claims secret-scan ## everything CI runs, no secrets needed
	@echo "verify: OK"

clean: ## remove the virtualenv and caches
	rm -rf $(VENV) .pytest_cache .ruff_cache
