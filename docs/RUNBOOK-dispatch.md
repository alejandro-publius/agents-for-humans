# Runbook additions from the dispatch session (laptop only)

## Known issue recorded for day-1.md

strands-agents 1.55.1: the after-model retry loop (a steering `Guide`
sets `AfterModelCallEvent.retry`) is `while True` inside one event-loop
cycle, so `limits={"turns": n}` never bounds a model that keeps producing
a rejected response. The package bounds every run with a per-run cap on
model calls (`build_agent(max_model_calls=24)`); at the cap, code composes
the plan and the evidence packet records `composed_by: "code"`. Keep the
cap when wiring the live model.

Two more, from the same investigation (`docs/UPSTREAM-NOTE.md`): a
steering handler that raises is treated as `Proceed` (our gates catch
their own errors and return `Guide`), and two `Guide`s in a row leave two
adjacent user turns, which Bedrock's alternating-roles rule would reject;
the same cap wrapper makes every request sendable at the first attempt
(`sendable_turns`: adjacent user text turns folded, the SDK's neutral
assistant turn placed after a tool result ahead of time), so keep the
wrapper on the live model. `make wire` runs the agent through the real
`BedrockModel` with a stand-in client that enforces those rules and
writes the request Bedrock will receive to
`docs/evidence/bedrock-request.json`; compare the first live request's
tools and system prompt with it if anything looks off.

Every target below makes AWS calls only with credentials present and an
explicit `--yes`. The dispatch session ran the `--dry-run` paths only.
Merge these sections into `docs/RUNBOOK.md`.

## The first live run (F19, F25, F26), in this order

Before any of it, `make rehearse` in the package: Sunday's whole offline
sequence in a scratch copy (exports named like the real ones, the two
variables, preflight, the policy check, every rerun, the docs check
failing until the fixture labels come off and passing after), about a
minute, nothing called. It runs in CI too.

0. `make preflight`: Python, the pinned Strands, the optional packages,
   the two exports (set `LE_KB_EXPORT` and `LE_CASES_EXPORT` first),
   credentials in the environment, the transcript. It calls nothing.
   Then the dress rehearsal of the two live scripts:
   `make demo-live DEMO_LIVE_ARGS=--stand-in` and
   `make eval-live EVAL_LIVE_ARGS=--stand-in`. Both run the live path
   exactly (a real `BedrockModel` per entry, every case through
   `deliver()`, the merge, the printed table) with the boto3 client
   replaced by a stand-in that plays a model reading the conversation
   (`le_dispatch/bedrock_wire.py`); nothing is called and the rows go to
   a file under the temp directory, never to `results/`. What to read
   from it: the shape of Sunday's output, and the cap at work: at the
   default 200 calls per entry the enforced entries stop after about 66
   cases (the stand-in's first guess costs one guide per case, three
   calls), the no-steering ones after 100; `--cap 1200` runs every case.
1. `make demo-live DEMO_LIVE_ARGS="--yes"`: one case, the first model in
   `evals/live_models.json`, about five model calls. Read the packet it
   prints: `composed_by` should be `model`; the gate events show what the
   model tried. If `composed_by` is `code`, the `reason` says why (a
   `StructuredOutputException` means the model would not call the Plan
   tool even when forced; a `ValidationException` mentioning "alternate"
   or "same turn" means the sendability passes missed a case, record it
   in day-1.md with the turn roles from the trace; an
   `AccessDeniedException` means the model id or the permission, one call
   spent, as `docs/evidence/bedrock-wire.md` shows).
2. `make demo-live DEMO_LIVE_ARGS="--yes --model us.amazon.nova-lite-v1:0"`
   for the second model.
3. `make eval-live EVAL_LIVE_ARGS=--yes`: four entries over the 194
   cases. The cap of 200 calls per entry (the work order's cost guard)
   covers about 100 cases at two calls each, so an entry stops early with
   `cases` around 100 and `stopped_early` set; the agreement is over the
   cases that ran, and the README table says how many. To run every case
   with room for retries: `EVAL_LIVE_ARGS="--yes --cap 1200"` (about 1200
   calls per entry, four entries); for a cheaper first pass:
   `EVAL_LIVE_ARGS="--yes --limit-cases 40"`. Time it before choosing: at
   two to four seconds per Bedrock call, 200 calls is about ten minutes per
   entry (forty for the four), 1200 about an hour per entry; the 40-case
   pass is a quarter of an hour in all and already gives every row a real
   number, labelled with its case count. The count is the whole story:
   every live client is built on `le_dispatch/live.py`, which switches
   botocore's own retry layer off (the default client would send a
   throttled request five times with backoff before the SDK ever saw it,
   uncounted) and bounds the SDK's strategy to four attempts with waits of
   2, 4 and 8 seconds, so a throttled call costs at most four requests and
   fourteen seconds and a hung stream sixty, after which code composes the
   plan; `make preflight` prints that line. Each case runs through
   `deliver()`; the entry reports `composed_by_code` (cases where the
   model never complied within 24 calls) and tokens used. Then `make
   results-table` and the claims update.
4. Commit `docs/evidence/live-*.md` and `results/policy_agreement.json`;
   flip the "pending" labels the README sections carry for the live rows.

## AgentCore Runtime: before `agentcore launch`

`make image-check` builds a virtualenv from
`infra/agentcore/runtime/requirements.txt` alone and, in it, imports the
entrypoint and the toolkit-facing app module, runs a quiet invocation and
a sent one with the scripted model, and builds the AgentCore app. It is
the image the toolkit builds, minus the container: a package the
entrypoint needs that the requirements file does not carry fails here in
about a minute instead of in the runtime's log after the launch. It runs
in CI on both Pythons. Then `make agentcore-deploy` for the toolkit steps
and the IAM list.

Sessions: invoke with one stable session id per rider
(`runtime_session_id(rider_id)`; the API wants at least 33 characters and
the helper makes one from the rider id and a digest), so the `pending`
state and the answer land on the same microVM; the
runtime reclaims an idle session (15 minutes of inactivity at the time
of writing), so the poll interval stays below that while a question is
open. The durable copies of the card and the answer are the poller's
(INTEGRATION.md 6b); the runtime's files are the session's, and the
session itself is deleted by the first quiet poll after the outage (the
conversation belongs to its outage; `session_reset` on the response), so
the S3 prefix holds live outages only.

## AgentCore Memory: the rider's decisions outlive the runtime session

A decision lives in `agent.state` (persisted by the Strands session
manager) and in the JSON mirror; on the runtime both belong to a session
the service reclaims when idle. `make agentcore-memory` prints the plan
for a Memory resource (`create_memory`, the case key indexed for the
filter, `eventExpiryDuration` equal to the retention rule's days), with
the call checked against the service model; on the laptop
`make agentcore-memory AGENTCORE_ARGS="--apply --yes"` creates it and
prints `LAST_ELEVATOR_MEMORY_ID`. With that variable set on the runtime
(and on the poller), `DecisionMemory` writes every answer through to the
Memory as one event under the rider's actor id and reads a case it does
not know from it, so "never asked twice" holds across runtime sessions
(`test_a_decision_survives_a_session_that_never_took_it`). The sent log
keeps its durable copy the same way ("sent" events, a "cleared" event when
the outage ends), and so does the decision itself (a "cleared" event when
the elevator is back: the next outage of the same elevator is a new
question, never held or sent on the old answer), so a fresh session reports `already_sent` instead of
sending the same plan again; and the inbox keeps its cards ("card"
events), so a session recycled while a question is open is followed by
one that reports `pending` with the same card instead of asking again;
the answer then ends the run with a plan the model drafts afresh under
the remembered answer (the paused run went with the old session, so
there is nothing to resume, and nothing is asked again). The stores' calls (`create_event`,
`list_events` with a metadata filter) are validated against the service
model as the tests make them. The durable copy is best effort and the
delivery is not: the runtime builds one client per container, wrapped in
`ResilientMemoryClient`, so a Memory call that fails degrades the copy
(the response's `memory` says `degraded` with the reason and the backlog,
the trace carries `memory.degraded`) while the invocation delivers from
the session's copy; a write that failed is replayed before the next call
with its original client token (every `create_event` carries one, derived
from the write, so a replay or a botocore retry never stores an event
twice), and the response says `replayed` when the copy has caught up. If
`memory` stays `degraded` across polls, check the runtime role's
permissions and the Memory's status before anything else; the riders are
still being served. The runtime role needs
`bedrock-agentcore:CreateEvent` and `ListEvents` on the Memory.

## AgentCore Observability

The runtime entrypoint calls `setup_observability()` before building the
app: when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (the starter toolkit's ADOT
configuration sets it on the deployed runtime), Strands' OTLP exporter is
enabled and every span the agent emits goes to CloudWatch, including the
custom gate events this package adds to them: `hook.cancel_tool`,
`steering.guide`, `steering.guide_after_model`,
`steering.proceed_after_model`, `interrupt.raised`, `interrupt.resumed`,
`delivery.composed_by_code`, `delivery.final_check_failed`,
`delivery.quiet`. In the CloudWatch trace view, filter on the event name
to see every time a gate fired in production; the evidence packet is the
same data, per decision, as a file. Offline nothing is configured (the
tests use an in-memory exporter, `le_dispatch/tracing.py`).

## AgentCore Policy (F5)

What it is: Policy in Amazon Bedrock AgentCore (GA March 3, 2026) stores
Cedar policies in a policy engine attached to an AgentCore Gateway. The
gateway evaluates every agent-to-tool request before allowing or denying
it, independently of the model. It governs only tool calls routed through
a Gateway, so the E7 MCP server becomes a gateway target and the agent
calls tools through the gateway URL.

Region: us-west-2. Confirm Policy and Gateway availability in the console
before the first apply; the launch region lists include us-west-2.

Steps:

1. Regenerate the Cedar from the frozen KB, not the fixture:
   export the KB to JSON in the documented shape (`le_dispatch/interfaces.py`,
   "KB JSON") from `kb/` at tag `kb-labels-v1`, then
   `python scripts/gen_cedar.py --kb path/to/kb-labels-v1.json`.
   Check `infra/agentcore/policy/manifest.json` says 50 stations, 97
   elevators, 5 labels, the real tag, and `local_validation: passed`
   (the policies are validated against `schema.cedarschema.json`, a schema
   in the shape the policy engine auto-generates from the gateway's tool
   definitions, so `FAIL_ON_ANY_FINDINGS` should pass at create time).
   Commit the regenerated files.
2. Fill `infra/agentcore/tools.json`: the tool names the E7 MCP server
   exposes and which parameters carry stations, elevators and options.
   The generator reads it; Cedar actions are `<target_name>___<tool>`.
3. Review the plan: `make agentcore-policy` (dry run). It prints every
   resource and the IAM permissions the operator needs, and ends with the
   service-model check: every call in the plan validated against the AWS
   service model botocore ships (parameter names, required members,
   enums, lengths), so a call the API would reject fails here, not on the
   apply. `make preflight` runs the same check over the policy and the
   evaluation and memory plans (twelve call shapes).
4. Apply, in order: `python scripts/agentcore_policy.py --apply --yes
   --gateway-role-arn <gateway service role> --mcp-endpoint <E7 URL>`.
   To attach to an existing gateway: add `--gateway-id <id>`; the apply
   path reads the gateway first (`get_gateway`) and passes its name, role
   and authorizer back into `update_gateway`, which the service requires
   (the check found the earlier plan sending the identifier alone).
   The apply path creates the engine, then the gateway (policies reference
   the gateway ARN), then the four policies with `FAIL_ON_ANY_FINDINGS`,
   then the MCP gateway target.
5. Smoke test through the gateway: call `draft_plan` with a KB station
   (expect allow) and with `station="ZZZZ"` (expect deny). Record both in
   `docs/reports/day-1.md` and flip the README line from "pending run".
6. If the docs require a Lambda wrapper for a FastMCP server as a target,
   swap `targetConfiguration` to `mcp.lambda` with an inline `toolSchema`
   built from `tools.json` (shape in the boto3 `create_gateway_target`
   reference) and note it in day-1.md.

Documented calls used (client `bedrock-agentcore-control`):
`create_policy_engine`, `create_policy` with
`definition={"cedar": {"statement": ...}}`, `create_gateway` /
`update_gateway` with `policyEngineConfiguration={"mode": "ENFORCE", "arn": ...}`,
`create_gateway_target` with `targetConfiguration={"mcp": {"mcpServer": {"endpoint": ...}}}`.

IAM permissions: see `python scripts/agentcore_policy.py --dry-run`.

Cost and cleanup: one policy engine, one gateway, one target, four
policies; delete with the console or `delete_gateway_target`,
`delete_gateway`, `delete_policy`, `delete_policy_engine` after the demo.

## AgentCore Evaluations (F6)

What it is: Evaluations in Amazon Bedrock AgentCore (GA March 31, 2026):
on-demand evaluation for programmatic testing and CI/CD gates, built-in
evaluators, ground-truth datasets, custom evaluators. Region: us-west-2;
confirm in the console.

Steps:

1. Regenerate the dataset from the frozen cases, not the fixture:
   `python scripts/agentcore_eval.py --dry-run --kb <kb export> --cases <cases export>`.
   It writes `evals/agentcore/dataset.json` (194 scenarios in the
   documented schema: scenario_id, turns[input, expected_response],
   expected_trajectory, assertions, metadata) and `evaluators.json`, and
   prints the plan. Commit both.
2. Deploy the custom evaluator once: `make evaluator-zip` writes
   `build/evaluator/option_equality.zip` (the one module, no
   dependencies, handler `option_equality.lambda_handler`), imports it
   from the zip alone in an isolated interpreter, runs it on real Strands
   spans with the reference input in the Evaluate API's shape, and prints
   the `aws lambda create-function` line (Python 3.11, timeout 60) and the
   `create_evaluator(evaluatorName="LastElevatorOptionEquality", level="TRACE",
   evaluatorConfig={"codeBased": {"lambdaConfig": {"lambdaArn": ..., "lambdaTimeoutInSeconds": 60}}})`
   call. The evaluations execution role needs lambda:InvokeFunction and
   lambda:GetFunction on the function. Put the ARN in `evaluators.json`.
2a. Read the three built-in evaluators for what they are: `Builtin.
   TrajectoryExactOrderMatch` against `["draft_plan", "Plan"]` scores
   first-try compliance (a run the gates had to correct has extra tool
   calls and scores zero even though the rider got the right plan);
   `Builtin.ToolSelectionAccuracy` scores each call; the custom
   option-equality evaluator scores the outcome, which is the number the
   README quotes. Report all three, and say which is which.
2b. The dataset's turn inputs start with the runtime payload as JSON (the
   poller's contract) followed by the scenario sentence; the deployed
   entrypoint accepts `{"prompt": <that text>}` as well as the bare
   payload, so the on-demand runner can hand each turn to the agent
   unchanged (confirm the runner's invocation shape once; a plain
   sentence naming the elevator that is out works too).
3. Confirm span attribute names against one real sessionSpans payload
   (invoke the deployed agent once, run `evaluate` with the custom
   evaluator, read the explanation). Extend `ARG_KEYS` in
   `option_equality.py` if AgentCore's tool spans use other names.
4. Run the on-demand evaluation per model and mode (enforced,
   no_steering) with the starter toolkit's
   `OnDemandEvaluationDatasetRunner` over the dataset, evaluator ids
   `Builtin.ToolSelectionAccuracy`, `Builtin.TrajectoryExactOrderMatch`,
   `Builtin.Correctness` and the custom ARN. Budget it: the dataset has
   194 scenarios, one turn each, and every invocation of the deployed agent
   is two or more model calls (a retry is one more), so a full run is
   about 600 calls per model and mode, four runs in all. Run a
   40-scenario slice first (the runner takes a subset of the dataset) and
   read one evaluation's explanation before the full runs.
5. Fold results: `scores_entry(results, model_id=..., mode=..., evaluator_id=...)`
   then `write_scores(entry)` appends to `results/policy_agreement.json`
   under provider "agentcore-evaluations" without touching local entries.
   Re-render the README table (F7) and update the claims.
