# Submission checklist: Last Elevator, Agents for Humans

Deadline: Monday, September 14, 2026, 5:00 PM PDT (8:00 PM EDT). Plan:
merge `overnight` into `main` Sunday night, submit Monday noon. Code stops
Sunday 6:00 PM PDT; after that, documentation only.

Status values: done, drafted (text exists, needs the laptop's numbers or
links), pending (laptop run), not started.

## Devpost requirements

| Requirement | Status | Owner | Where |
|---|---|---|---|
| Text description, guarantees-first, person sentence, Strands named | drafted | laptop fills TODOs | `docs/devpost.md` |
| Public repo URL | pending (repo public before submission) | owner | Devpost form |
| LICENSE (MIT) visible in the repo About panel | done in the main repo (D2); this package also ships MIT | owner | `LICENSE` |
| README a stranger could run cold | drafted sections; main README exists (D3) | laptop merges | `docs/README-sections.md` |
| Architecture diagram (UI, Strands loop, tools, AWS services, output) | done (D1); the dispatch package adds two full diagrams (one poll, the human moment) with Policy and Evaluations marked pending run | laptop merges | `docs/ARCHITECTURE.md`, `docs/architecture-additions.md` |
| Video under five minutes on YouTube or Vimeo, project working end to end | script drafted; shoot Saturday, cut Sunday | owner | `docs/video-script.md` |
| Built With tags include Strands Agents SDK, Amazon Bedrock, AgentCore | pending | owner | Devpost form |
| Builder ID email in the form | pending | owner | Devpost form |
| Testing access for judges (`make demo-one` offline; live URL) | offline done; live URL TODO | laptop (deploy C5) | README Testing section |
| Track selection: Everyday | pending | owner | Devpost form |
| Disclosure (all code Aug 10 to Sep 14, 2026, AI-assisted; pre-existing code listed) | drafted, "none known" to confirm | owner | README, devpost |
| No exposed API keys | done: secret scan in `make verify`, key-strip fixture, network guard | dispatch | `scripts/secret_scan.py` |
| Public or synthetic data only | done: three synthetic riders, synthetic fixtures, outage data only | dispatch | `fixtures/` |
| Bonus: up to three builder.aws.com posts, "Agents for Humans" in each title, before the deadline | drafted | owner publishes | `docs/posts/` |
| Real-user count in Accomplishments (even three people) | TODO | owner | devpost |
| Eight to ten screenshots | nine numbered in `docs/screenshots/` (`make screenshots`; 08, the axe audit, is the laptop's) plus twelve in `docs/diagrams/` (`make diagrams`); the devpost refers to the numbered ones; add the app's own screen and the live packet | owner | Devpost gallery |
| AgentCore runtime ARN printed in the submission | pending (deploy) | laptop | README, devpost |

## Laptop-only runs still pending

| Run | Command | Needs | Writes |
|---|---|---|---|
| Drop the package in | `make integrate INTO=~/agents-for-humans`, then `INTEGRATE_ARGS=--yes`; resolve the listed conflicts by hand | repo | `docs/dispatch-integration.json` |
| Preflight | `make preflight` (versions, packages, exports, credentials in the environment; calls nothing) | repo | terminal |
| Archive key check | `key in` archive step per RUNBOOK | archive data | day-1.md |
| AWS readiness | `aws ready` quota and smoke test | AWS credentials | day-1.md |
| KB and cases exports | exporters from `kb/` at `kb-labels-v1` (INTEGRATION step 2), then `export LE_KB_EXPORT=... LE_CASES_EXPORT=...` | repo | `kb/export/*.json` |
| Policy engine against the frozen cases | `make policy-check POLICY=<adapter>` (INTEGRATION 2a); fix any drift first | exports, the adapter | `results/policy_engine_agreement.json` (claimable) |
| Red team on the real KB | `make red-team` | exports | `results/red_team.json` (claimable) |
| Gate ablation on the real KB | `make ablation` | exports | `results/gate_ablation.json` (claimable) |
| Quiet metric on the archive replay | `make report` | archive replay | `results/quiet.json` (claimable) |
| Live evals, two models | `make eval-live EVAL_LIVE_ARGS=--yes` (the 200-call cap covers about 100 cases; `--cap 1200` for all 194, `--limit-cases 40` for a cheap first pass) | Bedrock access | `results/policy_agreement.json` rows |
| AgentCore Policy | `make agentcore-policy` (dry run), then `AGENTCORE_ARGS="--apply --yes ..."` and the allow/deny smoke test | AWS credentials, gateway role, E7 endpoint | day-1.md, README "pending run" flipped |
| AgentCore Evaluations | evaluator Lambda, `make agentcore-eval AGENTCORE_ARGS="--apply --yes ..."`, `write_scores` | AWS credentials, runtime ARN | `results/policy_agreement.json` rows |
| Public dataset | `make dataset DATASET_ARGS="--archive ... --query-file ..."` | archive data | `data/public/` |
| Deploy (C5) | per RUNBOOK, owner's explicit yes; `make agentcore-deploy` prints the toolkit steps for the dispatch entrypoint | AWS credentials | live URL, runtime ARN |
| Live smoke run for the video | `make demo-live DEMO_LIVE_ARGS="--yes"` (one case, about five model calls) | Bedrock access | `docs/evidence/live-<model>.md` |
| Upstream note | post `docs/UPSTREAM-NOTE.md` as a strands-agents issue, link it from the devpost text | GitHub | devpost "What we learned" |
| Claims merge | 43 dispatch rows into `scripts/verify_claims.py`, values updated after real runs | repo | CI |
| Merge `overnight` into `main` (D9) | Sunday night | owner | main |

## Dispatch PRs (standalone repo `last-elevator-dispatch`, one commit each, tests green on each)

| Item | Commit | State | Tests (cumulative) |
|---|---|---|---|
| F1 two-stage gate (steer_after_model), KB hook, scripted model, fixtures | 6156dfa | done, tarball and PR text delivered | 8 |
| F2 Interrupt for after-dark and last-train, decision card, inbox, decision memory, resume | e3b06f2 | done | 15 |
| F3 red team, `results/red_team.json`, claims wiring | 20087e6 | done (fixture run, not claimable) | 18 |
| F4 quiet metric, `results/quiet.json`, weekly report opening line | 8441650 | done (synthetic week, not claimable) | 21 |
| F5 AgentCore Policy scaffold: Cedar from the KB, local evaluation, dry run, runbook | e9fdb71 | done, deployment pending run | 27 |
| F6 AgentCore Evaluations scaffold: dataset, custom evaluator, dry run, results writer | 90e23c9 | done, run pending | 32 |
| F7 two-model eval-live config, hard cap, README table generator | 9636634 | done, live rows pending | 38 |
| F8 dataset export against a fixture archive | 9012df8 | done, real export pending | 41 |
| F9 submission text refresh, check-docs | 0115f3b | done, TODOs for the laptop | 41 |
| F10 this checklist and INTEGRATION.md | 8605e97 | done | 41 |
| F11 hardening: prose gate, five-kind and exhaustive red team, evaluator on real Strands spans | b102b06 | done | 45 |
| F12 persistence and validation: cross-process Interrupt resume, Cedar schema validation | fb0a67e | done | 48 |
| F13 evidence packets, EVIDENCE.md matrix, CI workflow, claims badge, inbox CLI | 9e5c401 | done | 50 |
| F14 feedback convergence study (seven personas times every case), prose fuzz test, make tour | db8501a | done | 60 |
| F15 AgentCore Runtime entrypoint, deployment plan, Cedar-versus-hook equivalence | 677682d | done | 63 |
| F16 mypy clean with typecheck in verify; prose option check; no re-ask while a question is pending | 506b12b | done | 65 |
| F17 approved rider messages (never a sentence the model wrote alone), injection and never-complies attacks, delivery fallback at a per-run cap | caef92c | done | 71 |
| F18 portability to another agency with zero code changes, onboarding guide, short default sentence | 91451dc | done | 76 |
| F19 live smoke run (dry run here), upstream note with an offline reproduction (executed as a test) and the fail-open finding, Strands surface table checked by check-docs, TL;DR blocks | 2c8d974 | done, live packet pending | 80 |
| F20 gate ablation study (nine configurations, six claims), plan-gate reasons name the right value | 0591a2b | done | 85 |
| F21 threat model, make judge, unaffected trips never run the model, video script and diagram refresh, test names checked in every document | 92de41d | done | 86 |
| F22 integration script (plan, copy, conflicts, report), integrate-check in CI, layout-independent tests and checks, Python 3.11 and 3.13 matrix | 58a828d, 671f8fe | done | 90 |
| F23 tour transcript generated and diffed in CI with every generated file, plan-gate reasons proven actionable over all cases, check-docs --only-dispatch, approval fuzz | 7565b73, ffe2dd8 | done | 93 |
| F24 the real AgentCore app (bedrock-agentcore SDK) serves /ping and /invocations in-process with the dispatch entrypoint; ruff format enforced | 623b6e2, 954ec69 | done | 94 |
| F25 live path hardened offline: forced structured output gated, approved sentences in the tool result, model id through the cap wrapper, live eval through deliver() with per-case fallback and entry-cap semantics | f5128ec, ebe15e4, 84ccc78, 4f94d96 | done | 98 |
| F26 adjacent user turns folded request-locally (Bedrock's alternating-roles rule after two rejections), third upstream observation | ab1dbf8 | done | 101 |
| F27 two environment variables switch every loader, script and writer to the real exports; results record their source and become claimable; check-docs flips its labels | 224d758 | done | 104 |
| F28 make preflight for the laptop | 49c5121 | done | 105 |
| F29 the card in plain words, optional station names in every sentence, open questions withdrawn when the outage ends | 8fc2941 | done | 109 |
| F30 locked, atomic inbox writes | 827457a | done | 110 |
| F31 retention rule and the read-aloud check over every case | 64f182f | done | 112 |
| F32 the cost of a decision on every outcome, packet and live-eval row | 4b83786 | done | 113 |
| F33 the architecture as two rendered diagrams | a23b1d0 | done | 113 |
| F34 the final check in the delivery layer, one outage one message, the accepted tool call on every packet | 11dce02, bef1220, f3c11e5 | done | 115 |
| F35 the real policy engine against the frozen cases (make policy-check), invalid payloads run nothing, the last line on the human-moment path | e33ad3c, a81415b, fab0148 | done | 120 |
| F36 AgentCore Observability wired (OTLP exporter when the runtime provides an endpoint), delivered_state on already_sent | f5b4dd1, f0fb79b, 868863b, 23ce5b3 | done | 121 |
| F37 the evaluation dataset runs against the deployed agent unchanged (prompt-shaped invocations, payload-first inputs, a judge-comparable expected response), the evaluators explained, check-docs verifies make targets | 0328400, 95f06a1, 62a1c27, 2da4165, 7eff65a | done | 123 |
| F38 the toolkit-facing app module and the image's requirements; credentials found in ~/.aws too (the tests never see them); the Plan's field descriptions for a live model | b4d4742, 5c03cea, bad1015, d8f5f99 | done | 125 |
| F39 integration guidance: handle() as the poller's path, pythonpath for the dispatch tests, the target list complete, clearer check-docs messages | 14a3210, 4d87701, 09f9a4c | done | 125 |
| F40 make rehearse (Sunday offline end to end, in CI); provider errors stop a live entry; live rows claimable only on the exports | e3a0d74, a543f9d, 79363ab, cdb7d5c | done | 127 |
| F41 make wire: the live path through the real Bedrock adapter with a stand-in client (the request on file, every retry sendable at the first attempt, errors costed); the eager tool-result separator in the cap wrapper; seven claims | 7c6b9f2, 2aa87ed, ddd2b82 | done | 144 |
| F42 make image-check: the runtime requirements in a fresh venv, the entrypoint and the app module invoked there, in CI | 3cc516c, e9f3129, 1ae9bae | done | 145 |
| F43 the live scripts' dress rehearsal (--stand-in on eval-live and demo-live: the live path with a stand-in client), in CI and in the rehearsal | 86259c7 | done | 148 |
| F44 every planned AWS call validated against botocore's service models offline; update_gateway, the session id length and the evaluator's reference-input shape fixed | 56e9580 | done | 154 |
| F45 the evaluator Lambda package built and verified from the zip alone; the local evaluation passes the API-shaped reference input | a687099 | done | 155 |
| F46 docs/SUNDAY.md: the laptop day in five time-boxed blocks with a cut list; the video script's optional wire beat | df4044f, a062eae | done | 155 |
| F47 the feedback loop closed on the wire: informative default prompt, the hook names the right values, the resumed pass asks once; human moment scenarios on the wire, four claims; the runtime state machine on the wire across invocations | 620b104, 7b14dae | done | 162 |
| F48 make wire-convergence: every persona through the real adapter in both tool-result formats, four claims | be804ef | done | 163 |
| F49 the wire rounded out: the forced structured-output path on file (one claim), a fuzz over every conversation shape Strands leaves, the upstream note's fourth observation, stand-in rows labelled in the table, one admit-and-reply for the stand-ins, the CI step unmasked | ed7bca7, 8206c1f, 60a4e2e, e7ff87d, 63af144, 84abf57, 2c5c03d | done | 165 |
| F50 make coverage: 95.2 percent line coverage by the offline tests, results/coverage.json, a floor claim, in CI | 2b5df3d, dcf9e71, 940769a | done | 166 |
| F51 the sentence and the card say where the outage bites (starting station, destination, transfer); read-aloud over every kind; the notification budget pinned | 699cdff, 9b9a540, 8d4fe35 | done | 166 |
| F52 AgentCore Memory for the rider's decisions, the sent log and the open questions (write-through, read-through; the plan and every call checked against the service model); the runtime reads LAST_ELEVATOR_MEMORY_ID and says composed_by; on the architecture diagram | f6a4509, e61f9ee, f08324a, 013b3d1 | done | 174 |
| F53 make demo-runtime: the entrypoint's every state offline, section 6 of the judge path and the transcript, an eleventh gallery image; the integration guide's target list enforced by check-docs | 3e062bb, 2695ba9, 816fd25 | done | 175 |
| F54 a question never blocks (the morning after supersedes an unanswered night question and sends the plan) and an answer never fails (a double tap, a changed mind, an answer to a question never asked here: a plain state, never an error); a recycled session's answer gets the model's plan | 89081df | done | 179 |
| F55 one retry layer on the live path, priced: every live client on le_dispatch/live.py (botocore's own retries off, a read timeout), Strands' strategy bounded to four attempts on every live agent; the stacked-layers finding (the fifth) in the upstream note with its flip test; make preflight prints the arithmetic | b9047e5 | done | 184 |
| F56 the durable copy is best effort, the delivery is not: ResilientMemoryClient (degraded on failure, the backlog replayed with idempotency tokens), the memory field on every runtime response, the outage on the runtime demo | 5d44951 | done | 187 |
| F57 a hung stream priced on the wire: one request, not retried, code composes; the tenth scenario, the 61st claim | 6cdf35e | done | 187 |
| F58 make runtime-sweep: every case through the runtime entrypoint with three riders each, 194 of 194 on every count, nine claims, section 7 of the judge path, CI and the rehearsal; the service models cached | 4895e4c | done | 190 |
| F59 a decision belongs to its outage: forgotten in every copy when the elevator is back (tombstones against the session copy), the next outage asked afresh; forgotten on every response, decision.cleared on the trace; the demo and the sweep walk it | 95817b9 | done | 192 |
| F60 the conversation belongs to its outage: the quiet poll deletes the trip's session (file or S3), the next outage starts clean; session_reset on the response, on the demo | 6124bff | done | 193 |
| F61 the package as git bundles in dependency order with notes and INDEX.md; the chain verified in a throwaway repo with make verify green (make bundles-check) | 4ecf3ad | done | 195 |
| F62 make video-assets: the command behind every on-screen moment with the lines to freeze on and the observed output (docs/video/commands.md), trace.png and eval_table.png | ef4a73c | done | 197 |
| F63 make screenshots: the numbered submission screenshots that need no laptop (eight of nine; the axe result is the laptop's), an index with who regenerates each, the devpost refers to them by number; the claims badge current | eeb223d | done | 198 |
| F64 make cold-start: the README's setup block replayed in a fresh venv on the bundle chain, the transcript in docs/reports/cold-start.md, two trips fixed | eb4aef0, 6259bd2, 13778f0 | done | 200 |
| F65 make demo-one-brief (the video's first shot in plain lines), the rubric self-score with the top five gaps, the two-pollers threat named | 86e8b35 | done | 201 |
| F66 make site: the evidence as a static site (every document a page, diagrams and screenshots in place), a Pages workflow; a URL a judge can click once Pages is on | 3e3a805 | done | 202 |
| F67 the hand-off: FINAL-INTEGRATION.md next to the bundles, HUMAN-CHECKLIST.md with times, the Devpost fields sheet, publish-ready posts, the field survey | 1e68383 | done | 202 |
| F68 make impact: what riders faced, from the outage archive (outages, stations, elevator-hours, evenings, stations cut off), five claims, the paragraph in the devpost | ff8c0c0 | done | 204 |
| F69 make serve: the runtime app locally on the stand-in, the curl line per state; the testing instructions for judges without a key | 48f3837 | done | 205 |
| F70 the rider's own words: RiderNote (a fixed vocabulary, quotes checked, feasibility only), the runtime's note field, the demo and the video beat | b9debac | done | 208 |
| F71 the first screen checked: the brief opens the tour, demo-live reads the note, alt text on every shipped image is a check-docs rule | e0b8273 | done | 209 |
| F72 make integrate-check green in the main repo's layout (four root-reading tests adapt), pipefail on every masked pipe in the checks | 0721e1c | done | 209 |
| F73 make integrate-ci: the placed workflow run in the integrated layout, the transcript in docs/reports/integrated-ci.md; the stale badge caught by a rule; bundles, cold-start and integrate-check pass without the package history | 6d53bb1 | done | 214 |
| F74 make site-a11y: axe-core over every page of the evidence site, zero violations as a claim, CI and Pages audit it; the two findings fixed; the badge and the claim-count phrases as check-docs rules | fcaedb8 | done | 217 |
| F75 the first paragraph (README, sections, devpost) and the voice-over as lines under twelve words, with a check-docs rule | 11bac09 | done | 218 |
| F76 post 2 under 900 words; every post under 900 and the publish-ready copies in step, as check-docs rules | 1e97034 | done | 219 |
| F77 docs/FAQ.md (the judge's questions, each answer pointing at its proof), the note curl line on make serve, the checklist wording | 45cefa3 | done | 219 |
| F78 dispatch.mk: every package target in one file the main Makefile includes with one line; the note property test over every case | f68e55a | done | 220 |
| F79 make first-shot: the brief as a GIF and a still under the README's first paragraph and on the site's front page | 0c12fb8 | done | 221 |
| F80 the README in the judge's order: the five-minute path and the setup before the index | 817415a | done | 221 |
| F81 a Codespace that opens on make verify; the self-score revised; the site's first-shot lines wrap | 93cebf1 | done | 222 |
| F82 every run count on the first page pinned to results, as a check-docs rule | 3dbb556 | done | 223 |
| F83 make judge said a minute and takes two, fixed everywhere; the still for reduced motion on the site | 361eb3c | done | 223 |
| F84 the archive replay wired into make report (--archive, --riders, --tz), rehearsed as the twenty-fifth step | c92af52 | done | 224 |
| F85 a make variable a document passes must be one a target reads (check-docs rule); make tour timed and said plainly | efa6d46, 22928bf | done | 225 |
| F86 the merge sections carry the first shot and the judge's five minutes; the README merge an explicit laptop step; ruff and mypy bounded | 421ffbd, f9acb30 | done | 225 |
| F87 the midday integrated CI run: a stale coverage file caught and regenerated, the transcript green; the form sheet and What's next current | dbdd899, 01bd878, 978114b, 5cbe1cd, 3e4a7ce | done | 225 |
| F88 make integrate --take: a named conflict replaced with the package's version, the main copy kept as .main-repo.bak | 615601a, 9936b73 | done | 225 |
| F89 the hostile note through the whole hosted contract, counted in the runtime sweep: orders change nothing 194/194, a real constraint removes one option and no more 194/194; two claims | 50765ad | done | 225 |
| F90 the note run as a fourth evidence packet with its diagram, on the site; the note row in the Strands tables | 0c1ca76, 7ddb260, fdf446a, 0618f62, 77181c5, c4b54b6 | done | 226 |
| F91 docs/video/storyboard.md: the script's sections with every voice line and the screen moments under their time, generated with the video assets | 88b9449 | done | 227 |
| F92 the note in the architecture diagram; the blocked items for day-1.md; the 10:00 integrated CI transcript green | 3fc3bdd, 12e81f4, d71d3e0, d6e0bc2 | done | 227 |
| F93 the quiet report names its week and riders; the FAQ's try-to-break-it section; What we learned closes with the note; the index wording | b95c4e7, fed53fa, d6e945a, 69badef, a60bedc | done | 227 |
| F94 make runtime-sweep-synthetic: the second agency's 48 cases through the same entrypoint, every counter 48/48, four claims | 3ccc950 | done | 228 |
| F95 the secret scan's git-less walk skips virtualenvs and caches (a downloaded zip with a venv inside failed it); verify green on 3.13 from the archive | f103466, 8038efc | done | 229 |
| F96 the secret scan's git-listed path skips compiled files and cache folders (the merge-day CI copy has no .gitignore and listed a .pyc with the folded example key); integrate-ci green | 6d03a4a, e8fc875, 82b0850 | done | 230 |
| F97 check-docs stays green while the owner fills Sunday night's words: the Devpost Links fields may hold values, a claimable live 100 percent row lifts the mock label, a post's filled links line is not a body change, --only-dispatch leaves the main README to its own rules, the label flip covers the FAQ and post 2, an off-slice wire convergence run lands beside the pinned file; six tests | 7e05608, b150dde, 901d0bc, 3ca8734, 5bae433 | done | 235 |
| F98 the main repo's CI after the real results land: the workflow reads the committed exports, the tests always read the fixtures, and a fixture run never overwrites a real results file (every writer); POLICY in the main Makefile; the rehearsal's label edit covers four documents | 442bc16 | done | 238 |
| F99 the tour transcript's header follows the run (the fixture label would have outlived the laptop's rerun on the Tour page) | 0b02db6 | done | 239 |
| F100 documents only: judge two to three minutes as measured, rehearse about seven, the evening checklist in durations | 59b3526 | done | 239 |
| F101 documents only: the merge-day lesson in What we learned, post 3 and the FAQ; the form guide's judge time; the compressed Monday-morning order in SUNDAY.md and the checklist | e322efb | done | 239 |
| F102 documents only: the first paragraph leads with the rider's avoided task, corrected against the code, in all three places | 11eeb68 | done | 239 |
| F103 make walkthrough: one outage end to end as a clickable page built from the packets, axe clean, published so a judge has a link before the deploy | d7875c4 | done | 241 |
| F0 reconciliation | skipped: not possible without the repo | laptop | |
