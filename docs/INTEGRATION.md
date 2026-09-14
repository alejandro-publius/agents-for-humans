# Integration: dropping last-elevator-dispatch into agents-for-humans

For the laptop session. The package was built without access to the
repo, so every repo dependency is an interface with a fixture. This page
says where each file goes, which make targets to add, and which
interface to wire to the real policy engine and KB. Do the wiring in the
order below; each step keeps `make verify` green.

## 0. Placement (recommended: sibling package, zero renames)

One command does the copy and refuses to overwrite anything:

```
make integrate INTO=~/agents-for-humans                       # plan: copy / identical / CONFLICT per file
make integrate INTO=~/agents-for-humans INTEGRATE_ARGS=--yes  # copy the non-conflicting files, write docs/dispatch-integration.json
make integrate INTO=~/agents-for-humans INTEGRATE_ARGS="--yes --take docs/devpost.md --take docs/video-script.md"
```

`scripts/integrate.py` maps every tracked file of this package to one
path in the main repo (the table below), skips files that already exist
with identical content, leaves a file that exists with different content
alone and lists it as a CONFLICT for you to merge by hand, never deletes,
and never reads `data/`. A conflict you want the package's version of is
named with `--take <package path>` (repeatable): the main repo's copy is
kept beside it as `<name>.main-repo.bak`, never overwritten, and the plan
prints the replacement before `--yes` does it. The Makefile, `pyproject.toml`, `README.md`,
`LICENSE` and `.gitignore` are not copied; the plan prints what to add.

| From (this repo) | To (agents-for-humans) | Notes |
|---|---|---|
| `le_dispatch/` | `le_dispatch/` at the repo root | importable as `le_dispatch.*` with no changes |
| `tests/*.py` | `tests/dispatch/` | additive; the dispatch `conftest.py` goes to `tests/dispatch/conftest.py`, so the network guard and the key strip apply to these tests without touching the main conftest; keep `tests/test_strands_mechanics.py` green |
| `scripts/*.py` | `scripts/` | if the main repo already has `scripts/verify_claims.py` it is reported as a CONFLICT: keep the main one and merge the `Claim` rows (step 6) |
| `fixtures/` | `fixtures/` | the package reads them relative to `le_dispatch/`; the laptop points the scripts at the real exports (step 2) |
| `infra/agentcore/` | `infra/agentcore/` | regenerate `policy/` from the real KB (step 2) |
| `evals/agentcore/`, `evals/live_models.json` | `evals/` | regenerate `agentcore/` from the real cases (step 2) |
| `results/*.json`, `results/badges/` | `results/` | fixture runs, `claimable: false`; the laptop reruns overwrite them |
| `results/policy_agreement.json` | not copied | the main file exists; `write_scores` and `merge_entries` merge rows into it |
| `docs/README-sections.md` | `docs/` | merge into `README.md` by hand (F9 PR text) |
| `docs/devpost.md`, `docs/video-script.md`, `docs/posts/` | `docs/` | a CONFLICT if the main drafts exist; keep whichever is further along, titles must carry "Agents for Humans" |
| the other `docs/*.md`, `docs/evidence/` | `docs/` | merge `RUNBOOK-dispatch.md` into `docs/RUNBOOK.md` by hand |
| `.github/workflows/verify.yml` | `.github/workflows/dispatch-verify.yml` | or merge its steps into the main workflow |
| `.github/workflows/pages.yml` | `.github/workflows/dispatch-pages.yml` | the evidence site to GitHub Pages; needs Pages switched on once |
| `dispatch.mk` | `dispatch.mk` | every target the package adds; one `-include dispatch.mk` line in the main `Makefile` (section 1) |
| `Makefile` | not copied | the main repo's own; it gains the include line |
| `pyproject.toml` extras `cedar`, `aws` | main project file | not copied; `cedarpy` for local Cedar evaluation, `boto3` is already a Strands dependency |

## 1. Makefile targets to add: one line

Every target the package adds lives in `dispatch.mk`, which `make
integrate` copies to the main repo's root. Add one line at the end of the
main `Makefile`:

```make
-include dispatch.mk
```

`dispatch.mk` defines `PY`, `PYTEST` and every `*_ARGS` variable with `?=`,
so values the main Makefile already sets win, and it sets `SHELL` to bash
for the recipes that need `pipefail`. The package's own `Makefile` includes
the same file, so the recipes CI runs are the ones the main repo gets; a
target added to the package appears in the main repo on the next
`make integrate`, and `make check-docs` refuses a document that names a
target neither file defines.

What stays the main Makefile's own: `install`, `test`, `lint`, `typecheck`,
`secret-scan`, `verify`, `verify-claims` (merged, section 6), `check-docs`
(the package's `scripts/check_docs.py`; pass `--only-dispatch`, which
leaves the main README and docs to their own rules, until they pass the
package's too), `demo-one` and `integrate`. The targets in
`dispatch.mk` call those by name (`judge` and `tour` run `verify` and
`demo-one`), so they must exist under those names. The targets that only
make sense with the package's own history (`bundles`, `cold-start`,
`integrate-check`) say so in the main repo and exit 0, so the placed CI
workflow stays green there.

pytest must find `le_dispatch/` at the repo root: add `pythonpath = ["."]`
under `[tool.pytest.ini_options]` in the main `pyproject.toml` (or run
with `PYTHONPATH=.`, as `make integrate-check` does). The scripts put the
repo root on `sys.path` themselves.

`scripts/integrate.py` itself stays in the dispatch package (it refuses to
run from an integrated repo).

CI: `.github/workflows/verify.yml` runs `make verify`, the exhaustive red
team and the local evaluation on every push, checks that the results
files are unchanged by the reruns (determinism), and uploads `results/`
and `docs/evidence/`. Merge its steps into the main workflow; the README
badge reads `results/badges/claims.json` from the raw GitHub URL
(replace TODO_OWNER and TODO_REPO). `make integrate-ci` in this package
runs every step of that workflow in the integrated layout (the copy
`make integrate` makes, with a Makefile of the main repo's own targets
plus the include line, and this pyproject, standing in) and writes
`docs/reports/integrated-ci.md`;
the steps that only make sense with the package's own history (`make
bundles`, `make cold-start`, `make integrate-check`) say so there and
pass.

Add `verify-claims` (merged) and `check-docs` to `make verify` if they are
not already there. The existing `make demo-one` keeps the main demo;
`demo-one-trace`, `demo-one-after-dark` and `demo-one-brief` come from
`dispatch.mk` and call `scripts/demo_one.py`.

## 2. The two exports (fixtures become real)

Write two small exporters in the main repo (or one script) that read the
frozen `kb/` package at tag `kb-labels-v1` and write:

- `KB_EXPORT` (`kb/export/kb-labels-v1.json`): `{"source", "frozen_tag":
  "kb-labels-v1", "stations": [...50], "elevators": [...97],
  "option_labels": [the five labels in BART's order], "station_names":
  {"DELN": "El Cerrito del Norte", ...}}` (the names are optional; with
  them, the rider hears "El Cerrito del Norte elevator DELN-E1 is out"
  instead of a code spelled letter by letter)
- `CASES_EXPORT` (`kb/export/cases-v1.json`): `{"cases": [{"case_id",
  "station", "elevator", "label", "option_text", "added_minutes",
  "source_url"}]}` for the 194 options.

Then point the whole package at them with two environment variables:

```
export LE_KB_EXPORT=kb/export/kb-labels-v1.json
export LE_CASES_EXPORT=kb/export/cases-v1.json
make red-team red-team-exhaustive convergence ablation agentcore-eval-local evidence transcript agentcore-policy-gen agentcore-eval
```

Every loader (`load_kb`, `load_cases`, `fixture_policy`) and every script
reads them; unset, the fixtures are used. Every results file's provenance
records the `source` it read and sets `claimable` only when both exports
were real (a mixed run is not claimable). Once `results/red_team.json` is
claimable, `make check-docs` requires the "fixture run" and "pending the
laptop rerun" labels to be gone from the README sections, the devpost
text, the FAQ and post 2, so the docs cannot lag the data. `gen_cedar.py`,
`agentcore_eval.py`, `agentcore_eval_local.py` and `eval_live.py` also
accept `--kb` and `--cases` explicitly. The labels stay frozen: the
exporters read, never write.

Commit both export files. The placed workflow's first step sets the two
variables when `kb/export/kb-labels-v1.json` and `kb/export/cases-v1.json`
exist, so the reruns in CI read what the laptop read and its determinism
check (every regenerated file byte-identical to the committed one) keeps
passing after the real results land; without them it says so and reads
the fixtures. The tests read the fixtures either way (`tests/conftest.py`
unsets the variables), so `make verify` is the same on both. A results
file a real run wrote is never overwritten by a fixture run: every
writer goes through `write_results_json`, which leaves the file as
committed and prints that it did when the file is claimable (or holds
the archive's week) and the run is not, so a target typed without the
exports or without `--archive`, and CI, which has no archive, keep the
laptop's numbers.

## 2a. The policy engine against the frozen cases

Once the adapter in section 3 exists, `make policy-check
POLICY=package.module:real_policy` runs the real engine and the
case-backed policy over every frozen case and writes
`results/policy_engine_agreement.json`; any disagreement (affectedness,
station, elevator, top option, minutes) is listed case by case and the
target exits 1. Two claims pin 194 cases and zero disagreements, so a
drift between the engine and the labels fails `make verify` before any
number downstream is cited. Without `POLICY` the check runs the
case-backed policy against itself (plumbing proof, not claimable). Set
`POLICY := package.module:real_policy` in the main `Makefile` above the
include line, so the placed workflow runs the real engine on every push
and a drift between the engine and the labels fails CI, not a judge.

## 3. The policy callable

`le_dispatch.interfaces.PolicyCallable` is `policy(trip: Trip) ->
PolicyDecision`. Write one adapter in the main repo:

```python
from le_dispatch.interfaces import PolicyDecision, RankedOption, Trip

def real_policy(trip: Trip) -> PolicyDecision:
    d = policy_engine.decide(saved_trip=..., outages=trip.outages)   # the existing pure-code engine
    return PolicyDecision(
        affected=d.affected, kind=d.kind, station=d.station, elevator=d.elevator,
        top_option=d.top.label if d.top else None,
        ranked=[RankedOption(o.label, o.feasible, o.reason, o.added_minutes, o.source_url) for o in d.ranked],
        flags={"after_dark": d.after_dark, "last_train": d.last_train},
        source_url=d.top.source_url if d.top else "",
    )
```

`Trip` carries `rider_id`, `origin`, `destination`, `outages`, `via`,
`after_dark`, `last_train`; map the app's saved trip onto it. Minutes and
flags must come from the engine; the gates compare against them.

## 4. The KB set

`KBSet(stations=frozenset(kb.station_codes()), elevators=frozenset(kb.elevator_ids()))`
built from the `kb/` package, or `load_kb(KB_EXPORT)`. Pass it to
`build_agent`, `KBHook`, `run_red_team`, `generate` (Cedar) and the
exporters.

## 5. The agent stack

The shortest path for the poller is one call per rider and trip:
`handle(payload, model_factory=..., kb=..., policy=..., session_manager_factory=...)`
from `infra/agentcore/runtime/entrypoint.py`, the same function the
deployed runtime serves. It carries every rule the runtime holds: the
open question withdrawn when the elevator is back, one outage one message
(`already_sent`, no model run), a bad payload runs nothing, the last check
before anything reaches the rider, the sent log and the inbox under a
lock. Building the stack by hand (below) is for callers that need
something the runtime does not offer.

`le_dispatch.gates.build_agent(model, kb, policy, trip, steering=True)`
returns the full stack (hook, both gates, structured output). Either use
it directly in the main agent wiring, or keep the main repo's agent and
attach `KBHook(kb)` via `hooks=[...]` and `PlanGateHandler(kb=kb,
policy=policy, trip=trip)` plus `DecisionInterruptHandler(...)` via
`plugins=[...]`, with `structured_output_model=Plan`. If the main repo's
plan tool is not named `draft_plan` or its Plan class is not `Plan`, pass
`plan_tool=` and `plan_model=` to the handlers and extend `tools.json`.

Session persistence: pass the main repo's session manager as
`session_manager=` to `build_agent` / `build_decision_run` (one session id
per rider and trip, for example `le-<rider>-<origin>-<destination>`). The
paused run, its messages and `agent.state["last_elevator.decisions"]`
then survive a process boundary: the poller pauses, the app answers, a
later poll resumes with `DecisionRun(...).resume(answer)` from the inbox
card, which carries the Strands interrupt ids. Proven with
`FileSessionManager` in `tests/test_interrupts.py`; the JSON mirror stays
for the app. Inbox: point `Inbox(path)` at the rider
app's store, or adapt the app to read `{"cards": [...]}` and post
answers with `Inbox.answer(case_key, bool)`.

Trace renderer: add `steering.guide_after_model`,
`steering.proceed_after_model`, `interrupt.raised`, `interrupt.resumed`
to the known event names in `docs/traces/`.

## 6. Results and claims

`le_dispatch/claims.py` holds 84 `Claim` rows over 15 results files (the
red team and its exhaustive run, the quiet week, the dataset and the
local evaluation, convergence, the ablation, the policy check, the wire
and its convergence, coverage, the runtime sweep for BART and for the
synthetic agency, the outage week, the site audit; the tuple at the top
of the module names each file). Merge them into the main
`scripts/verify_claims.py` table (41 rows at last report). After each
real run, update the expected values to the real numbers (`make
verify-claims` names every row that no longer holds, with the actual
value beside the expected one; a count that moves with the export, such
as the dataset's stations and elevators, moves in the row) and flip
`provenance.claimable` by rerunning the target (the writers set it from
the run). Live policy-agreement rows merge into the existing
`results/policy_agreement.json` via `merge_entries` / `write_scores`.

## 6a. Rider messages

The rider message is never a sentence the model wrote alone.
`le_dispatch/messages.py` composes a few approved sentences from the
policy decision and the KB row's own option text; the plan gate accepts
only one of them verbatim (whitespace and trailing punctuation
normalized). The `draft_plan` tool result carries them as
`approved_messages`, so a live model sees them before its first Plan and
the plan-gate rejection repeats them for a model that did not read the
tool result; keep that field if the main repo's draft tool replaces this
one. Keep that in the app: what the rider sees is
`plan.rider_message`, which is always an approved sentence or, when the
model never complied, the first one, composed by code (`composed_by:
"code"` in the outcome and the evidence packet). If the main repo prefers
model-written prose, pass `approved_messages=False` to `build_agent`; the
prose checks (minutes, codes, other option names) still run, but an
injected sentence with no numbers and no codes would pass, which is why
the strict default exists.

## 6b. The runtime entrypoint

`infra/agentcore/runtime/entrypoint.py` is the AgentCore Runtime
entrypoint: `handle(payload)` takes the trip (an optional answer, an
optional `note` in the rider's own words) and returns quiet, sent, held or
pending with the plan or the decision card, and what the note ruled out.
It defaults to a `FileSessionManager` per rider and trip so a pause
survives invocations on one container; on the deployed runtime pass
`session_manager_factory=` with `S3SessionManager`. The conversation
belongs to its outage: a quiet poll (nothing out on the trip) deletes
the trip's session through the manager's `delete_session`, so the next
outage starts a clean conversation and the store does not grow with a
rider's history (`session_reset` on the quiet response). Inject the real KB and
policy engine with `kb=` and `policy=`, and the Bedrock model with
`bedrock_model_factory(model_id, region)` (it builds the model through
`le_dispatch.live.model`, the client configuration every live path
shares: botocore's own retries off, a read timeout; `make_runtime` puts
the bounded `le_dispatch.live.retry_strategy()` on every run, so a
throttled call costs at most four requests and fourteen seconds). The file the starter toolkit
points at is `infra/agentcore/runtime/app.py` (a module-level `app` built
from the environment) with `infra/agentcore/runtime/requirements.txt` as
the image's dependencies, run from the repo root so the image carries
`le_dispatch/`. `make agentcore-deploy` prints
the toolkit steps (`agentcore configure`, `agentcore launch`, `agentcore
invoke`) and the IAM list; the runtime ARN it prints goes in the README.
Before `agentcore launch`, `make image-check`: a fresh virtualenv from
the requirements file alone, the entrypoint and the app module imported
and invoked there, so a missing dependency shows up on the laptop in a
minute rather than in the container's log. When the main repo's poller
adds imports to the entrypoint's path, add their packages to the
requirements file and run the check again.

Sessions on the runtime. AgentCore Runtime isolates each
`runtimeSessionId` in its own microVM and reclaims an idle one after a
while (15 minutes of inactivity at the time of writing, 8 hours at
most; check the current limits). The pause and the resume of the human
moment must land on the same session: invoke with one stable session id
per rider (`runtime_session_id(rider_id)` from `le_dispatch/interfaces.py`;
the API requires at least 33 characters, so the helper appends a digest
to the rider id; pass it as the toolkit's `--session-id` option or the
`runtimeSessionId` parameter of `InvokeAgentRuntime`), and keep the poll
interval below the idle limit while a question is open. The inbox, the
sent log and the decision memory under `LAST_ELEVATOR_DATA` are the
session's copy; the rider's answer reaches the runtime through the
payload (`answer`), and the `pending` response carries the card, so the
poller and the app hold the durable copies (the main repo's store) and
the runtime needs no shared filesystem. For a session that outlives the
microVM, pass `session_manager_factory` with `S3SessionManager` so the
Strands conversation survives; the card is re-sent from the poller's
copy. The rider's decisions and the sent log have their own durable
store: with `LAST_ELEVATOR_MEMORY_ID` set, `handle()` builds an
`AgentCoreDecisionStore` and an `AgentCoreSentStore` per rider
(`le_dispatch/agentcore_memory.py`); `DecisionMemory` writes every answer
through to AgentCore Memory and reads a case it does not know from it,
`SentLog` does the same for what was delivered (a "cleared" event when
the outage ends), and `Inbox` for the cards, so a fresh session neither
asks twice nor sends twice, and an open question survives a recycled
session (the answer then ends the run with a plan the model drafts
afresh under it, nothing asked again); the stores call the service
through `ResilientMemoryClient`, so an outage degrades the durable copy
(the response's `memory` field) and never fails a delivery, and the
failed writes replay, once, when it is back; `make agentcore-memory` prints the plan and creates the Memory on
the laptop. The poller can use the same stores (`decision_store_factory=`
on `handle()`, or the classes directly) so its copies and the runtime's
agree.

## 7. Laptop-only runs, in order

1. `make integrate INTO=~/agents-for-humans` (plan), then with
   `INTEGRATE_ARGS=--yes`; resolve the listed conflicts by hand; `make
   verify` in the main repo with the package in place. `make
   integrate-check` in this package is the same copy into an empty tree
   followed by the dispatch tests and checks, and runs in CI.
2. Exports (step 2), then `make red-team`, `make report
   REPORT_ARGS="--archive data/archive/<file>.sqlite --query-file <sql>"`
   (the archive's week replayed; `--riders <json>` for real trips), `make
   agentcore-policy` (dry run), `make agentcore-eval` (dry run): commit the
   regenerated `infra/agentcore/policy/`, `evals/agentcore/` and the three
   results files.
3. `make eval-live EVAL_LIVE_ARGS=--yes` with Bedrock credentials (two
   models, two modes; the 200-call cap covers about 100 cases at two calls
   each, `--cap 1200` runs all 194 with room for retries), then `make
   results-table` into the README.
4. `make agentcore-policy AGENTCORE_ARGS="--apply --yes --gateway-role-arn ... --mcp-endpoint ..."`
   and the allow/deny smoke test; `make agentcore-eval AGENTCORE_ARGS="--apply --yes ..."`
   after the evaluator Lambda exists; fold scores with `write_scores`.
5. `make dataset DATASET_ARGS="--archive data/archive/<file>.sqlite --query-file <sql>"`.
6. Deploy (C5), fill the README placeholders, `make verify`, merge
   `overnight` into `main` Sunday night.
