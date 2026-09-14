# Sunday, September 13: the laptop day, time-boxed

Code stops at 6:00 PM PDT; after that, documentation only. Submission
Monday noon (deadline Monday 5:00 PM PDT). Everything below is a laptop
run; the dispatch package has rehearsed the offline half (`make rehearse`,
twenty-five steps) and the live half with a stand-in (`--stand-in`), so each
block starts from a command that already passed here. Times are
estimates from this session's runs; the live ones scale with Bedrock's
latency (two to four seconds a call).

## Block 0, 9:00 to 9:30: the package in the main repo

1. `make integrate INTO=~/agents-for-humans` (plan; read the CONFLICT
   lines), then `INTEGRATE_ARGS=--yes`; add `-include dispatch.mk` to the
   main Makefile (and `POLICY := <adapter>` above it once block 1's
   adapter exists, so CI runs the real engine), the extras and the
   `.gitignore` lines from `docs/INTEGRATION.md` section 1.
2. `make verify` in the main repo. Green before anything else.
3. The two exports from `kb/` at `kb-labels-v1`
   (`docs/INTEGRATION.md` section 2), committed at `kb/export/` so CI
   reads them too; `export LE_KB_EXPORT=... LE_CASES_EXPORT=...`.
4. `make preflight` (calls nothing; twelve planned AWS calls checked
   against the service model, and the retry arithmetic of the live path:
   at most four requests and fourteen seconds per throttled call), `make
   rehearse` (about seven minutes), then
   `make eval-live EVAL_LIVE_ARGS=--stand-in` and
   `make demo-live DEMO_LIVE_ARGS=--stand-in` (five seconds).

Stop rule: a red `make verify` in the main repo is fixed before block 1;
nothing else is.

## Block 1, 9:30 to 10:15: the numbers on the real data

1. `make policy-check POLICY=<adapter>` (`docs/INTEGRATION.md` 2a). Any
   disagreement is fixed (the engine or the labels) before a number is
   cited.
2. `make red-team red-team-exhaustive convergence ablation
   agentcore-eval-local evidence transcript wire wire-convergence
   runtime-sweep agentcore-policy-gen agentcore-eval`, then `make report
   REPORT_ARGS="--archive data/archive/<file>.sqlite --query-file <sql>"`
   (the archive's week replayed for the synthetic riders; `--riders` for
   real trips) and `make impact IMPACT_ARGS="--archive
   data/archive/<file>.sqlite --query-file <sql>"` (what riders faced,
   from the feed; the paragraph in the devpost updates from the file). About six minutes offline (the sweep
   is a minute and a half of it). If there is time,
   `make wire-convergence WIRE_CASES=194` (five minutes) covers every
   real case through the adapter and lands in
   `results/wire_convergence_194.json`; the 24-case slice in
   `results/wire_convergence.json` is what the claims pin, and stays.
3. Drop the "fixture run" and "pending the laptop rerun" labels in the
   README sections, the devpost text, the FAQ and post 2 (both copies);
   `make check-docs` refuses to pass until they are gone once
   `results/red_team.json` says `claimable: true`, and names each file.
   Commit the regenerated files.

## Block 2, 10:15 to 11:00: the first live calls

1. `make demo-live DEMO_LIVE_ARGS="--yes"` (one case, the Sonnet
   profile, about five calls), then `--model us.amazon.nova-lite-v1:0`.
   Read the packet: `composed_by: model`, or the `reason` says why
   (`docs/RUNBOOK-dispatch.md`, the first live run). Commit
   `docs/evidence/live-*.md`.
2. `make eval-live EVAL_LIVE_ARGS="--yes --limit-cases 40"` (about a
   quarter of an hour for the four entries): every row gets a real
   number, labelled with its case count. Then choose: the full run
   (`--cap 1200`, about an hour per entry) in a second terminal while
   block 3 runs, or the 40-case rows as the submission's numbers. Both
   are honest; the table says the case count.
3. `make results-table` into the README when the run you chose is done.

## Block 3, 11:00 to 1:00: AgentCore

1. `make image-check` (a minute), then `make agentcore-deploy` for the
   steps: `agentcore configure -e infra/agentcore/runtime/app.py -r
   infra/agentcore/runtime/requirements.txt`, `agentcore launch`,
   `agentcore invoke` twice with the same `--session-id`
   (`runtime_session_id(rider_id)`, at least 33 characters): `pending`,
   then `sent`. The runtime ARN goes in the README.
2. `make agentcore-policy AGENTCORE_ARGS="--apply --yes
   --gateway-role-arn ... --mcp-endpoint ..."` (the dry run has already
   validated every call against the service model), then the allow and
   deny smoke test through the gateway. Record both in day-1.md.
   `make agentcore-memory AGENTCORE_ARGS="--apply --yes"` (one call),
   then `LAST_ELEVATOR_MEMORY_ID` on the runtime before `agentcore launch`
   so the rider's decisions outlive the session; optional, the cut list
   has it.
3. `make evaluator-zip`, the `aws lambda create-function` line it
   prints, `create_evaluator`, the ARN into `evals/agentcore/evaluators.json`;
   then the on-demand evaluation over `evals/agentcore/dataset.json`
   and `write_scores` (`docs/RUNBOOK-dispatch.md`, Evaluations).

## Block 4, 1:00 to 2:30: the public dataset and the words

1. `make dataset DATASET_ARGS="--archive data/archive/<file>.sqlite
   --query-file <sql>"`; commit `data/public/`.
2. Post `docs/UPSTREAM-NOTE.md` as a strands-agents issue; link it from
   the devpost "What we learned".
3. README placeholders: video URL, live URL, runtime ARN, post URLs,
   the real-user count. `make verify` and `make check-docs` in the main
   repo.

## Block 5, 2:30 to 6:00: the video, the merge, the margin

1. Cut the video from the Saturday footage and the screen recordings
   (`docs/video-script.md`; the honesty checks at its end).
2. `make judge` one last time; merge `overnight` into `main`.
3. The margin is for whatever broke. Nothing new starts after 5:00 PM.

## The cut list, in order, if a block runs over

1. The full `eval-live` run: keep the 40-case rows (they are labelled
   with the case count; the runbook explains the cap).
2. The AgentCore Evaluations run: keep the dataset, the local evaluator
   result on real spans (`results/agentcore_eval_local.json`) and the
   dry-run plan, all labelled pending.
3. The gateway smoke test: keep the generated Cedar, its local
   validation, and the hook-versus-Cedar equivalence test.
4. The public dataset export: keep the fixture-backed `make dataset`
   and say so.
5. The AgentCore Memory resource: keep the decisions in the session and
   the mirror (the plan and the tests stand); say the store is pending.

Never cut: block 0, the policy check, the label flip, one live packet,
the runtime deployment (the ARN is a submission requirement), the video.

## If the laptop day is Monday morning instead

The order stands and the clock compresses. The never-cut items fit in
about two and a half hours in this order: block 0 (thirty minutes;
`make verify` green in the main repo before anything else), the exports
and `make policy-check POLICY=<adapter>` (fifteen), the offline reruns
with the label flip (fifteen), one `make demo-live DEMO_LIVE_ARGS="--yes"`
packet (five), `make image-check` and `agentcore launch` for the ARN
(forty-five), then the README merge and the placeholders (twenty),
`make verify` and `make judge` (five), merge and push. Everything on the
cut list is cut before it starts, and the words say pending where they
already do. Submit by noon with what is green; a post edit on Devpost is
allowed until the cutoff, a code change is not.

## What does not happen on Sunday

No new feature. No AWS call outside the commands above. No number in
the text that a results file does not carry. No `--yes` on a command
whose dry run has not been read.
