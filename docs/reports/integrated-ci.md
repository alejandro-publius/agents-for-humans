# The main repo's CI, run in the integrated layout

`make integrate-ci` on 2026-09-13 23:58 UTC: `scripts/integrate.py` copied the package into an empty tree the way
it lands in `agents-for-humans` (`tests/dispatch/`, `docs/`, no package README, no package Makefile),
the package's README, Makefile and pyproject stood in for the main repo's own (the targets and extras
the owner adds by hand, `docs/INTEGRATION.md` section 1), the tree became a git repository, and every
`run:` line of
`.github/workflows/verify.yml` (the workflow `make integrate` places as `dispatch-verify.yml`) ran
there in order. The install step is this environment. Exit codes and last lines below; paths in the
scratch tree are shortened. Anything red here would be red on the main repo's Actions page after the
merge, which is the first page some judges open.

Integrate: `copied 222 files; report at docs/dispatch-integration.json`.

## the exports, when the repository has them (the laptop's real results came from them; the reruns below must read them too, or the determinism check would compare real numbers with fixture ones)

`if [ -f kb/export/kb-labels-v1.json ] && [ -f kb/export/cases-v1.json ]; then printf 'LE_KB_EXPORT=%s/kb/export/kb-labels-v1.json\nLE_CASES_EXPORT=%s/kb/export/cases-v1.json\n' "$PWD" "$PWD" >> "${GITHUB_ENV:-/dev/null}"; echo "exports found, the reruns read kb/export/ (the tests read the fixtures either way)"; else echo "no kb/export/, the reruns read the fixtures and every results file says so"; fi`: exit 0, 0s

```
no kb/export/, the reruns read the fixtures and every results file says so
```

## verify (lint, mypy, tests with the network blocked and keys stripped, secret scan, claims, docs)

`make verify`: exit 0, 122s

```
ok  site.a11y.pages              pages >= 30 (actual 35)
claims verified: 84/84
python3 scripts/check_docs.py
check-docs: ok (37 documents, 3 posts, 84 claims referenced)
verify: ok
```

## red team, exhaustive (every case times every attack)

`make red-team-exhaustive`: exit 0, 30s

```
  hostile calls: 14356
  caught: hook_cancel=388 guide_before_tool=3104 guide_after_model=9506
  reached rider: hallucinated_stations=0 wrong_options=0 minutes_not_from_policy=0 unapproved_messages=0
  plans delivered: 2716 (composed by code after the turn cap: 194)
wrote results/red_team_exhaustive.json (claimable: False)
```

## custom evaluator on real Strands spans

`make agentcore-eval-local`: exit 0, 2s

```
make[1]: Entering directory ''
python3 scripts/agentcore_eval_local.py
local evaluation on real Strands spans: 194/194 PASS, option found in {'Plan:gen_ai.tool.message.content': 194} (claimable: False)
wrote results/agentcore_eval_local.json
```

## feedback is actionable (nine personas times every case)

`make convergence`: exit 0, 13s

```
  prose_station      converged 194/194  max 3  mean 3.0  hist {'3': 194}
  own_words          converged 194/194  max 3  mean 3.0  hist {'3': 194}
  injection          converged 194/194  max 3  mean 3.0  hist {'3': 194}
  everything_wrong   converged 194/194  max 5  mean 5.0  hist {'5': 194}
wrote results/adaptive_convergence.json (claimable: False)
```

## gate ablation (regenerates results/gate_ablation.json)

`make ablation`: exit 0, 17s

```
without_any_gate              140        40      40      80         80          140  24/54 12/2.0
zero leaks: all_gates, without_before_tool_gates, without_kb_hook, without_option_gate, without_plan_prose
leaks: without_after_model_gate, without_any_gate, without_plan_approval, without_plan_fields
every configuration delivered every plan: True
wrote results/gate_ablation.json (claimable: False)
```

## the policy engine against the frozen cases (the case-backed policy against itself here)

`make policy-check`: exit 0, 0s

```
make[1]: Entering directory ''
python3 scripts/policy_check.py 
policy engine agreement: 194/194 cases (100.0% of the plumbing proof), 0 disagreement(s), source URL differs on 0
wrote results/policy_engine_agreement.json (claimable: False)
```

## the live path through the real Bedrock adapter, offline (regenerates results/bedrock_wire.json)

`make wire`: exit 0, 2s

```
hung                 composed by code  calls  1 requests  1 rejected 0
prose_then_forced    composed by model calls  3 requests  3 rejected 0
human_moment_yes     composed by model calls  3 requests  3 rejected 0
human_moment_no      composed by model calls  3 requests  3 rejected 0
wrote docs/evidence/bedrock-request.json, docs/evidence/bedrock-wire.md, results/bedrock_wire.json (fixture KB)
```

## every convergence persona through the real adapter, per model id (regenerates results/wire_convergence.json)

`make wire-convergence`: exit 0, 41s

```
make[1]: Entering directory ''
python3 scripts/wire_convergence.py --cases 24
us.anthropic.claude-sonnet-4-5-20250929-v1:0     converged 216/216 within 5 calls
us.amazon.nova-lite-v1:0                         converged 216/216 within 5 calls
wire convergence: 432/432 runs (24 cases x 9 personas x 2 model ids), max 5 calls, 0 requests rejected; wrote results/wire_convergence.json (fixture KB)
```

## every case through the runtime entrypoint, offline (regenerates results/runtime_sweep.json)

`make runtime-sweep`: exit 0, 319s

```
  after dark, no: held with status hold 194/194, the next poll already_sent 194/194; the elevator back, the no forgotten 194/194, out again, asked afresh 194/194
  kinds: cannot_enter 65, cannot_exit 65, transfer 64
  AgentCore Memory stand-in: 3104 events, status ok, every call well formed
  on the trace: decision.cleared 194, interrupt.raised 582, interrupt.resumed 194, interrupt.superseded 194
wrote results/runtime_sweep.json (fixture KB)
```

## the second agency through the same entrypoint (regenerates results/runtime_sweep_synthetic.json)

`make runtime-sweep-synthetic`: exit 0, 57s

```
  after dark, no: held with status hold 48/48, the next poll already_sent 48/48; the elevator back, the no forgotten 48/48, out again, asked afresh 48/48
  kinds: cannot_enter 16, cannot_exit 16, transfer 16
  AgentCore Memory stand-in: 768 events, status ok, every call well formed
  on the trace: decision.cleared 48, interrupt.raised 144, interrupt.resumed 48, interrupt.superseded 48
wrote results/runtime_sweep_synthetic.json (synthetic agency)
```

## a stranger's first hour (the bundles into an empty repository, a fresh venv, the README's setup block)

`make bundles cold-start COLD_START_ARGS=--skip-judge`: exit 0, 0s

```
python3 scripts/bundles.py 
bundles: nothing to build here: this is the integrated layout (tests/dispatch/); the bundles are built in the package
python3 scripts/cold_start.py --skip-judge
bundles: nothing to build here: this is the integrated layout (tests/dispatch/); the bundles are built in the package
cold-start: no bundles to replay here (the chain is built in the dispatch package, whose CI replays it)
```

## the runtime image's requirements carry everything the entrypoint needs (a fresh venv from that file alone)

`make image-check`: exit 0, 19s

```
make[1]: Entering directory ''
python3 scripts/image_check.py
installing infra/agentcore/runtime/requirements.txt into a fresh virtualenv (nothing else)
probe: ok (quiet, sent, the app built twice) on python 3.11.15 with strands-agents 1.55.1, pydantic 2.13.5, bedrock-agentcore 1.23.0; observability: none (OTEL_EXPORTER_OTLP_ENDPOINT unset)
image-check: ok (19s)
```

## the evidence site through axe-core in Chromium (regenerates results/site_a11y.json; a violation fails)

`make site-a11y`: exit 0, 17s

```
make[1]: Entering directory ''
python3 scripts/site_a11y.py 
site-a11y: built 35 pages under build/site
site-a11y: 35 pages, 913 checks passed, 0 violations (0 rules); axe-core 4.12.1
wrote results/site_a11y.json
```

## the live scripts' dress rehearsal (the live path with a stand-in client; nothing called, never a result)

`make eval-live EVAL_LIVE_ARGS=--stand-in && make demo-live DEMO_LIVE_ARGS=--stand-in > /tmp/demo-live-stand-in.txt && tail -3 /tmp/demo-live-stand-in.txt`: exit 0, 4s

```
  not claimable: a stand-in client stood in for Bedrock; plumbing proof only
wrote /tmp/le-eval-live-stand-in.json (stand-in rows)

wrote /tmp/le-demo-live-stand-in/stand-in-us-anthropic-claude-sonnet-4-5-20250929-v1-0.md (model calls: 3)
```

## the custom evaluator as a Lambda package, verified from the zip alone

`make evaluator-zip`: exit 0, 1s

```
verified: imported from the zip alone in an isolated interpreter, real spans: {'label': 'PASS', 'value': 1.0, 'explanation': "agent chose 'alternate_elevator' (Plan:gen_ai.tool.message.content), matching the KB label"}

laptop steps (nothing below has been executed):
1. aws lambda create-function --function-name last-elevator-option-equality --runtime python3.11 --handler option_equality.lambda_handler --zip-file fileb://build/evaluator/option_equality.zip --role <lambda execution role arn> --timeout 60 --region us-west-2
2. create_evaluator(evaluatorName='LastElevatorOptionEquality', level='TRACE', evaluatorConfig={'codeBased': {'lambdaConfig': {'lambdaArn': <function arn>, 'lambdaTimeoutInSeconds': 60}}}); the evaluations execution role needs lambda:InvokeFunction and lambda:GetFunction on it; put the ARN in evals/agentcore/evaluators.json
```

## the integrated layout works (tests/dispatch/, scripts/, docs/ in an empty tree)

`make integrate-check`: exit 0, 0s

```
make[1]: Entering directory ''
integrate-check: this is the integrated layout already; nothing to copy
```

## Sunday rehearsed offline (the exports switch, every rerun, the docs-label flip, in a scratch copy)

`make rehearse`: exit 0, 442s

```
ok   check-docs must FAIL: results are claimable, labels still say fixture   2.6s    - docs/posts/02-agents-for-humans-two-stage-gate.md: results/red_team.json is claimable (real exports) but t
ok   check-docs after the label edit                1.8s  check-docs: ok (37 documents, 3 posts, 84 claims referenced)
ok   results say claimable and name the exports     0.0s  claimable True kb/export/kb-labels-v1.json

rehearsal: ok (25/25 steps)
```

## the AgentCore Memory plan (dry run, the call checked against the service model)

`make agentcore-memory`: exit 0, 0s

```
  - bedrock-agentcore:CreateMemory, GetMemory (the operator, once)
  - bedrock-agentcore:CreateEvent, ListEvents, GetEvent on the memory (the runtime role and the poller)

service-model check: the call above is well formed (botocore)
credentials present: True (dry run makes no calls either way)
```

## generated policies, dataset, evidence packets, the transcript and the claims badge

`make agentcore-policy-gen agentcore-eval evidence transcript impact && python scripts/verify_claims.py --badge`: exit 0, 71s

```
ok  sweep_synthetic.note_orders  note_orders_ignored == 48 (actual 48)
ok  sweep_synthetic.failures     failures == [] (actual [])
ok  site.a11y.violations         violations == 0 (actual 0)
ok  site.a11y.pages              pages >= 30 (actual 35)
claims verified: 84/84
wrote results/badges/claims.json
```

## every generated file is unchanged by the reruns (deterministic)

`git diff --exit-code -- results/ docs/evidence/ docs/TOUR-TRANSCRIPT.md infra/agentcore/policy/ evals/agentcore/`: exit 0, 0s

```
(no output)
```

## line coverage of the package by the offline tests (results/coverage.json, regenerated and diffed on 3.11)

`make coverage && git diff --exit-code -- results/coverage.json`: exit 0, 147s

```
  le_dispatch/evidence.py                           88.9%  (9 lines missing)
  le_dispatch/adaptive.py                           90.8%  (20 lines missing)
  le_dispatch/policy_check.py                       93.1%  (4 lines missing)
  le_dispatch/messages.py                           94.3%  (3 lines missing)
wrote results/coverage.json
```

Result: every step exited 0.
