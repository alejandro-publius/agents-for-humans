# dispatch.mk: every make target the dispatch package adds, in one file the main repo includes.
#
#   -include dispatch.mk        # one line at the end of agents-for-humans/Makefile; make integrate copies this file
#
# The package's own Makefile includes it too, so the recipes here are the ones CI runs, in either layout.
# Variables the main Makefile may already define keep their values (?=).
PY ?= python3
PYTEST ?= $(PY) -m pytest
SHELL := /bin/bash
.PHONY: walkthrough first-shot runtime-sweep-synthetic demo-one-trace demo-one-after-dark demo-one-brief fixtures red-team red-team-exhaustive report agentcore-policy-gen agentcore-policy agentcore-memory agentcore-eval eval-live results-table dataset agentcore-eval-local evidence badge convergence tour demo-runtime judge integrate-check integrate-ci transcript preflight retention diagrams policy-check wire wire-convergence video-assets screenshots cold-start serve impact site site-a11y bundles bundles-check runtime-sweep coverage image-check evaluator-zip rehearse agentcore-deploy ablation demo-live

demo-one-trace:
	$(PY) scripts/demo_one.py --trace

demo-one-after-dark:
	$(PY) scripts/demo_one.py --after-dark

DEMO_ONE_ARGS ?=
demo-one-brief:
	$(PY) scripts/demo_one.py --brief $(DEMO_ONE_ARGS)

fixtures:
	$(PY) scripts/make_fixtures.py

# red-team: defined in the main Makefile, byte-identical to this file's ($(PY) scripts/red_team.py).
# Dropped here so including this file adds no overriding-recipe warning to every make invocation.

red-team-exhaustive:
	$(PY) scripts/red_team.py --exhaustive

REPORT_ARGS ?=
report:
	$(PY) scripts/quiet_report.py $(REPORT_ARGS)   # REPORT_ARGS="--archive data/archive/<file>.sqlite --query-file <sql>" on the laptop

# F5: Cedar from the KB export; ARGS defaults to --dry-run, the laptop passes ARGS="--apply --yes ..."
AGENTCORE_ARGS ?= --dry-run
agentcore-policy-gen:
	$(PY) scripts/gen_cedar.py

agentcore-policy: agentcore-policy-gen
	$(PY) scripts/agentcore_policy.py $(AGENTCORE_ARGS)

# AgentCore Memory for the rider's decisions: the plan (dry run, the call checked against the service model);
# the laptop passes AGENTCORE_ARGS="--apply --yes" to create the Memory and gets LAST_ELEVATOR_MEMORY_ID
agentcore-memory:
	$(PY) scripts/agentcore_memory.py $(AGENTCORE_ARGS)

# F6: dataset export plus the plan; dry run by default, the laptop passes AGENTCORE_ARGS="--apply --yes ..."
agentcore-eval:
	$(PY) scripts/agentcore_eval.py $(AGENTCORE_ARGS)

# F7: two models x two modes, 200-call cap; prints the entries and calls nothing without credentials and --yes
EVAL_LIVE_ARGS ?=
eval-live:
	$(PY) scripts/eval_live.py $(EVAL_LIVE_ARGS)

results-table:
	$(PY) scripts/render_results_table.py

# F8: public CSV from an outage archive; default builds the fixture archive, the laptop passes DATASET_ARGS
DATASET_ARGS ?=
dataset:
	$(PY) scripts/export_dataset.py $(DATASET_ARGS)

# F11: the custom evaluator on real Strands spans, offline
agentcore-eval-local:
	$(PY) scripts/agentcore_eval_local.py

# F13: evidence packets (JSON plus markdown with a sequence diagram) and the claims badge
evidence:
	$(PY) scripts/evidence_packet.py > /dev/null
	$(PY) scripts/evidence_packet.py --after-dark --answer yes > /dev/null
	$(PY) scripts/evidence_packet.py --after-dark --answer no > /dev/null
	$(PY) scripts/evidence_packet.py --note "no ramps today, I am pushing a stroller" > /dev/null
	@echo "wrote docs/evidence/"

badge:
	$(PY) scripts/verify_claims.py --badge | tail -2

# F14: is the gates' feedback actionable? nine wrong-from-the-start personas times every case
convergence:
	$(PY) scripts/convergence.py

# the four-minute tour for the video: every gate, the human moment, the counts
tour:
	@echo "== 1. every gate fires (make demo-one-brief, make demo-one-trace) =="; $(PY) scripts/demo_one.py --brief; echo; $(PY) scripts/demo_one.py --trace | awk '/hook cancels/{p=1} p'
	@echo; echo "== 2. the human moment (make demo-one-after-dark) =="; $(PY) scripts/demo_one.py --after-dark | awk '/^run 1 state/{p=1} p' | grep -E '^(run|rider|plan)|"question"'
	@echo; echo "== 3. the counts (make red-team, make report, make convergence) =="; $(PY) scripts/red_team.py | awk 'NR<=5'; $(PY) scripts/quiet_report.py | awk 'NR==1'; $(PY) scripts/convergence.py | awk 'NR==1'

# the runtime entrypoint's whole state machine, offline: the learner through the real adapter, the Memory stand-in
demo-runtime:
	$(PY) scripts/demo_runtime.py

# the judges' path in one command: verify, the tour, the ablation, wire and runtime tables (about two minutes, offline)
judge:
	@set -o pipefail; start=$$(date +%s); $(MAKE) --no-print-directory verify | tail -1; echo; $(MAKE) --no-print-directory tour; echo; \
	echo "== 4. which gate protects what (make ablation) =="; $(PY) scripts/ablation.py | awk 'NR>=2 && NR<=14'; \
	echo; echo "== 5. the live path through the real Bedrock adapter, offline (make wire) =="; $(PY) scripts/bedrock_wire.py | awk 'NR<=11'; \
	echo; echo "== 6. the runtime entrypoint, every state, offline (make demo-runtime) =="; $(PY) scripts/demo_runtime.py | awk 'NR>=4'; \
	echo; echo "== 7. the hosted contract over the dataset, a 24-case slice here, all 194 in results/ (make runtime-sweep) =="; $(PY) scripts/runtime_sweep.py --cases 24 --out /tmp/le-runtime-sweep-slice.json | awk 'NR<=8'; \
	echo; echo "judge: done in $$(( $$(date +%s) - start ))s; next read docs/FAQ.md, docs/evidence/DELN-E1-daytime.md, docs/EVIDENCE.md, docs/THREAT-MODEL.md, docs/evidence/bedrock-wire.md"

# the integrated layout works: copy into an empty tree (with a stand-in for the main repo's policy_agreement.json),
# then run the dispatch tests, check-docs and verify-claims from that tree
integrate-check:
	@if [ -d tests/dispatch ]; then echo "integrate-check: this is the integrated layout already; nothing to copy"; exit 0; fi; \
	set -o pipefail; rm -rf .integrate-check && mkdir -p .integrate-check/results && \
	cp results/policy_agreement.json .integrate-check/results/policy_agreement.json && \
	$(PY) scripts/integrate.py --into .integrate-check --yes | tail -1 && \
	cd .integrate-check && PYTHONPATH=. $(PY) -m pytest tests/dispatch -q -p no:cacheprovider && \
	  $(PY) scripts/check_docs.py && $(PY) scripts/verify_claims.py | tail -1 && $(PY) scripts/ablation.py --n-per-attack 1 | tail -1; \
	  status=$$?; cd "$(CURDIR)" && rm -rf .integrate-check; [ $$status -eq 0 ] && echo "integrate-check: ok"; exit $$status

# the CI workflow the main repo receives, run step by step in the integrated layout (about a quarter of an hour)
integrate-ci:
	$(PY) scripts/integrated_ci.py $(INTEGRATE_CI_ARGS)

# the tour and the ablation table as a document, for a judge who reads instead of runs; deterministic, diffed in CI
transcript:
	@{ echo "# Tour transcript (generated by make transcript; do not edit)"; echo; \
	   $(PY) scripts/transcript_header.py; echo; \
	   echo '```'; $(MAKE) --no-print-directory tour; echo; echo "== 4. which gate protects what (make ablation) =="; \
	   $(PY) scripts/ablation.py | awk 'NR>=2 && NR<=14'; echo; \
	   echo "== 5. the live path through the real Bedrock adapter, offline (make wire) =="; \
	   $(PY) scripts/bedrock_wire.py | awk 'NR<=11'; echo; \
	   echo "== 6. the runtime entrypoint, every state, offline (make demo-runtime) =="; \
	   $(PY) scripts/demo_runtime.py | awk 'NR>=4'; echo; \
	   echo "== 7. the hosted contract over the dataset, a 24-case slice here, all 194 in results/ (make runtime-sweep) =="; \
	   $(PY) scripts/runtime_sweep.py --cases 24 --out /tmp/le-runtime-sweep-slice.json | awk 'NR<=8'; echo '```'; } > docs/TOUR-TRANSCRIPT.md
	@echo "wrote docs/TOUR-TRANSCRIPT.md"

# the laptop's readiness for the live runs: versions, packages, exports, credentials in the environment; calls nothing
preflight:
	$(PY) scripts/preflight.py

# the retention rule: closed cards and evidence packets older than DAYS under DATA_DIR; dry run unless RETENTION_ARGS=--yes
DATA_DIR ?= /tmp/last-elevator
DAYS ?= 30
RETENTION_ARGS ?=
retention:
	$(PY) scripts/retention.py --data-dir "$(DATA_DIR)" --days $(DAYS) $(RETENTION_ARGS)

# the two architecture diagrams as SVG and PNG (needs mermaid-cli; GitHub renders the markdown itself)
diagrams:
	$(PY) scripts/diagrams.py

# the real policy engine against the frozen cases: make policy-check POLICY=package.module:callable
# (without POLICY the case-backed policy is checked against itself, the plumbing proof)
POLICY ?=
policy-check:
	$(PY) scripts/policy_check.py $(if $(POLICY),--policy $(POLICY),)

# the live path through Strands' real Bedrock adapter with a stand-in client: the request Bedrock receives,
# every retry sendable, what an error costs; writes docs/evidence/bedrock-*.{json,md} and results/bedrock_wire.json
wire:
	$(PY) scripts/bedrock_wire.py

# the convergence study through the real Bedrock adapter, per model id (24 cases x 9 personas x 2 ids, about
# half a minute); writes results/wire_convergence.json; WIRE_CASES=194 for every case (about five minutes,
# written to results/wire_convergence_194.json so the pinned slice and its claims stand)
WIRE_CASES ?= 24
wire-convergence:
	$(PY) scripts/wire_convergence.py --cases $(WIRE_CASES)

# the command behind every on-screen moment of the video, run here, with the lines to freeze on; two renders
video-assets:
	$(PY) scripts/video_assets.py

# the numbered screenshots for the submission that need no laptop (docs/screenshots/, with an index)
screenshots:
	$(PY) scripts/screenshots.py

# the video's first shot as a GIF and a still (docs/screenshots/00-first-shot.*), from make demo-one-brief
# one outage end to end as a page a judge can click through with nothing installed, built from the four
# committed evidence packets and the results files (build/walkthrough/index.html, and artifact.html for a host
# that supplies the document shell)
walkthrough:
	$(PY) scripts/walkthrough.py

first-shot:
	$(PY) scripts/first_shot.py

# a stranger's first hour, replayed: the bundles into an empty repository, a fresh venv, the README's setup block
# as written; the transcript goes to docs/reports/cold-start.md (about six minutes; needs the package index)
COLD_START_ARGS ?=
cold-start:
	$(PY) scripts/cold_start.py $(COLD_START_ARGS)

# the AgentCore Runtime app on this machine, on the learner stand-in: no key, no call; curl the contract
serve:
	$(PY) scripts/serve.py

# what riders faced, from the feed: the outage archive summarised (results/outage_week.json); the laptop passes
# IMPACT_ARGS="--archive data/archive/<file>.sqlite --query-file <sql>"
IMPACT_ARGS ?=
impact:
	$(PY) scripts/impact.py $(IMPACT_ARGS)

# the evidence as a static site (build/site/index.html): every shipped document as a page, the diagrams and
# screenshots in place, ready for GitHub Pages (.github/workflows/pages.yml)
site:
	$(PY) scripts/site.py

# axe-core over every page of the evidence site (results/site_a11y.json; exit 1 on a violation)
site-a11y:
	$(PY) scripts/site_a11y.py $(SITE_A11Y_ARGS)

# the package as git bundles for the laptop (build/bundles/, INDEX.md, one note per bundle); --check applies the
# chain in a throwaway repo and runs make verify there (about three minutes)
BUNDLES_ARGS ?=
bundles:
	$(PY) scripts/bundles.py $(BUNDLES_ARGS)
bundles-check:
	$(PY) scripts/bundles.py --check $(BUNDLES_ARGS)

# every case through the runtime entrypoint, offline (about a minute and a half); results/runtime_sweep.json
SWEEP_CASES ?= 0
runtime-sweep:
	$(PY) scripts/runtime_sweep.py --cases $(SWEEP_CASES)

# the second agency's cases through the same entrypoint (results/runtime_sweep_synthetic.json; about a minute)
runtime-sweep-synthetic:
	$(PY) scripts/runtime_sweep.py --agency synthetic

# line coverage of the package by the offline tests (coverage.py; about the suite's run time); results/coverage.json
coverage:
	$(PY) scripts/coverage_report.py

# the runtime image's requirements file carries everything the entrypoint needs: a fresh virtualenv from that
# file alone, then the entrypoint and the app module imported and invoked there (needs pip's index; about a minute)
image-check:
	$(PY) scripts/image_check.py

# the custom evaluator as a Lambda deployment package (build/evaluator/option_equality.zip), imported from the
# zip alone in an isolated interpreter and run on real spans before it is uploaded; prints the laptop steps
evaluator-zip:
	$(PY) scripts/evaluator_zip.py

# Sunday, offline, end to end: the exports switch, every rerun, the docs-label flip, in a scratch copy
rehearse:
	$(PY) scripts/rehearse.py

# F15: the runtime deployment plan (dry run; the laptop runs the toolkit)
agentcore-deploy:
	$(PY) scripts/agentcore_deploy.py

# F20: which gate protects what; the red team and a convergence slice with gates removed one at a time
ablation:
	$(PY) scripts/ablation.py

# F19: one case on a live Bedrock model through the same gates, with an evidence packet.
# Dry run by default (calls nothing); the laptop passes DEMO_LIVE_ARGS="--yes"
DEMO_LIVE_ARGS ?=
demo-live:
	$(PY) scripts/demo_live.py $(DEMO_LIVE_ARGS)
