# Final integration package, for the laptop session

Written by the dispatch session on Sunday morning. This is the whole sequence for the laptop session that
owns `~/agents-for-humans`, the archive, the credentials and every command that needs AWS: apply the
bundles, run the gated live steps in order, fill the numbers, regenerate the live screenshots, open the
pull request, deploy, and print what the owner publishes. `docs/SUNDAY.md` is the timed version of the
middle; this file is the order of operations end to end. Every command here exists in the package's
Makefile or is the main repo's own; nothing here is typed from memory.

## 0. Apply the bundles (block 0, before 9:30)

From the folder that holds the dispatch session's Outputs (the `bundles/` folder inside it):

```
cd <outputs>/bundles
git -C ~/agents-for-humans fetch origin overnight
git -C ~/agents-for-humans checkout overnight
```

Then every fetch line in `INDEX.md`, top to bottom (each keeps the commit hashes and touches no working
file), then the integration block at the end of `INDEX.md` (archive the last ref, `make integrate` plan,
`make integrate` with `--yes`, the branch `dispatch/f-block`, the commit, `make verify` in the main repo).
A CONFLICT the plan lists on a document the package has taken further (the devpost, the video script, a
post) is resolved with `--take <package path>`: the main repo's copy stays beside it as `.main-repo.bak`.
Add by hand what `make integrate` reports as not copied: one `-include dispatch.mk` line at the end of
the main Makefile (every target the package adds is in that file, which `make integrate` copied), a
`POLICY := <adapter>` line above it once block 1's adapter exists (so the placed workflow runs the real
engine on every push), the extras and the `.gitignore` lines from `docs/INTEGRATION.md` section 1. A red `make verify` in the main repo is fixed
before anything else. `docs/reports/integrated-ci.md` is the placed workflow run step by step in that
layout the day before (`make integrate-ci` in the package); if a step is red on the main repo's Actions
page after the merge and green there, the difference is the main repo's own Makefile or pyproject.

## 1. The numbers on the real data (block 1)

1. The two exports from `kb/` at `kb-labels-v1` (`docs/INTEGRATION.md` section 2), committed at
   `kb/export/kb-labels-v1.json` and `kb/export/cases-v1.json` so the placed workflow reads them and its
   determinism check holds after the real results land; `export LE_KB_EXPORT=... LE_CASES_EXPORT=...`.
2. `make preflight` (nothing called: the credentials, the region, the twelve planned AWS calls against
   the service model, the retry arithmetic), `make rehearse` (offline, twenty-five steps), `make
   eval-live EVAL_LIVE_ARGS=--stand-in`, `make demo-live DEMO_LIVE_ARGS=--stand-in`.
3. Archive confirmation: `make report REPORT_ARGS="--archive data/archive/<file>.sqlite --query-file
   <sql>"` (the archive's week replayed for the synthetic riders; the quiet report's opening line becomes
   the real week's; add `--riders <json>` shaped like `fixtures/riders.json` for real trips), `make impact
   IMPACT_ARGS="--archive data/archive/<file>.sqlite --query-file <sql>"` (what riders faced, from the
   feed; the devpost paragraph is checked against the file), and a read of the archive's date range; the
   number of real riders for the README. Both files then hold the archive's numbers, and a fixture run
   (a `make impact` or `make report` typed without the arguments, or CI, which has no archive) leaves
   them as committed.
4. `make policy-check POLICY=<adapter>`; any disagreement is fixed before a number is cited.
5. `make red-team red-team-exhaustive convergence ablation agentcore-eval-local evidence transcript wire
   wire-convergence runtime-sweep agentcore-policy-gen agentcore-eval`; if there is time, `make
   wire-convergence WIRE_CASES=194` (it writes `results/wire_convergence_194.json`; the pinned 24-case
   slice and its claims stand).
6. Drop the "fixture run" labels in the README sections, the devpost text, the FAQ and post 2 (its draft
   and its publish-ready copy); `make check-docs` refuses to pass until `results/red_team.json` says
   `claimable: true` and the labels are gone, and names each file. Commit the regenerated files.

## 2. Quota, smoke test, the live runs (block 2)

1. Quota: the Bedrock model access for the two model ids in `evals/live_models.json` in the configured
   region, and the account's requests-per-minute for each; `make preflight` prints the retry arithmetic
   (a throttled call costs at most four requests and fourteen seconds).
2. Smoke test: `make demo-live DEMO_LIVE_ARGS="--yes"` (one case, the first model, about five calls), then
   `DEMO_LIVE_ARGS="--yes --model us.amazon.nova-lite-v1:0"`. Read the packet: `composed_by: model`, or the
   `reason` says why. Commit `docs/evidence/live-*.md`.
3. `make eval-live EVAL_LIVE_ARGS="--yes --limit-cases 40"` (both models, both modes, about a quarter of
   an hour), then `make results-table` into the README. The full run (`--cap 1200`) in a second terminal
   during block 3 if there is time; the table says the case count either way.
4. Red team on the real knowledge base is already in step 1.5; the a11y audit of the rider app is the
   main repo's own target and its result is `docs/screenshots/08-axe.png`.
5. `make dataset DATASET_ARGS="--archive <file> --query-file <file>"` for the public dataset.

## 3. AgentCore, dry run then real (block 3)

1. `make image-check`, then `make agentcore-deploy` (the toolkit steps and the IAM list, printed, nothing
   run), then the steps themselves: `agentcore configure -e infra/agentcore/runtime/app.py -r
   infra/agentcore/runtime/requirements.txt`, `agentcore launch`, `agentcore invoke` twice with the same
   session id (`runtime_session_id(rider_id)`): `pending`, then `sent`. The runtime ARN goes in the README.
2. `make agentcore-policy` (the dry run, every call validated), then `make agentcore-policy
   AGENTCORE_ARGS="--apply --yes --gateway-role-arn <arn> --mcp-endpoint <url>"` and the allow and deny
   smoke test through the gateway.
3. `make agentcore-memory` (dry run), then `make agentcore-memory AGENTCORE_ARGS="--apply --yes"`; put the
   printed memory id in `LAST_ELEVATOR_MEMORY_ID` on the runtime and launch again.
4. `make evaluator-zip`, the `aws lambda create-function` line it prints, `create_evaluator`, the ARN into
   `evals/agentcore/evaluators.json`; `make agentcore-eval AGENTCORE_ARGS=--dry-run`, then `make
   agentcore-eval AGENTCORE_ARGS="--apply --yes --agent-runtime-arn <arn>"`; fold the scores with
   `write_scores`.

## 4. The numbers into the words

0. Merge `docs/README-sections.md` into the main `README.md` by hand, in its order: the first paragraph
   (the person, the guarantee, the number, the human moment) and the first-shot GIF at the top, the TL;DR,
   the judge's five minutes, the guarantees, the numbers, the product; the placeholders at the end. The
   main README is what the judges open; this package's own README stays the package's.
1. The main repo's `scripts/fill_placeholders.py` for the placeholders the live results fill (the README
   table, the devpost's live rows, the runtime ARN, the real-user count); `make check-docs` then verifies
   every figure against `results/`. The claims badge in the merged README reads
   `results/badges/claims.json` from the raw GitHub URL: replace `TODO_OWNER` and `TODO_REPO` in it, or
   the badge renders as broken on the first page.
2. `make badge video-assets screenshots site site-a11y` so the badge, the eval table render, the numbered
   screenshots (02, 04, 05, 07, 09) and the evidence site carry the live rows, and the site is audited
   again with the live pages in it; add `08-axe.png` from the a11y audit and a shot of the app's own
   decision card.
3. `make coverage` (regenerates `results/coverage.json`, which CI diffs; any change to `le_dispatch/` or the
   runtime moves the statement count), then `make verify` and `make judge` one last time.

## 5. The pull request, the deploy, the printouts (block 5)

1. The pull request from `overnight` to `main` with `docs/SUBMISSION-CHECKLIST.md` as its description;
   merge tonight; flip the repository public; confirm the About panel shows the MIT license.
2. Switch GitHub Pages on (Settings, Pages, Source: GitHub Actions); the push to `main` publishes the
   evidence site; its URL goes into the devpost's Links and the README.
3. The deploy: the rider app per the main repo's runbook (C5), the live URL into the README and the form.
4. Print for the owner: the three posts from `docs/posts/publish-ready/` (the last line of each takes the
   repo and video URLs), the Devpost fill from `docs/reports/forms/devpost-fields.md`, and the human
   checklist `docs/HUMAN-CHECKLIST.md`.

## Stop rules

- Nothing is claimed as a result until the command that produces it has run here; every results file
  says `claimable: true` only after step 1.6.
- No number in any document that is not read from `results/`; `make check-docs` is the referee.
- The cut list in `docs/SUNDAY.md` applies if a block runs over: the full eval-live run first, then the
  Evaluations run, the gateway smoke test, the public dataset, the Memory resource. Nothing new starts
  after 5:00 PM; the code stops at 6:00 PM.
