# Threat model: what Last Elevator assumes, defends, and does not

An agent for a rider who depends on elevators has one failure that
matters: a wrong plan that the rider trusts. Everything below is judged
against that. Each defended threat names the gate that stops it, the
test that proves it, the ablation row that shows the gate is the one
doing the work, and the red-team counter that would move if it failed.
Undefended threats are listed too, with what stands in for a defense.

## Trust boundaries

Trusted: the frozen knowledge base (`kb-labels-v1`, 194 options labelled
by two people from BART's station pages), the policy engine (pure code:
affectedness, BART's published option order, minutes), the outage feed as
a source of facts about which elevators are out, and the rider's own
saved trips and answers.

Not trusted: the model (any model), any text the model reads (the feed's
free text, a station page, a tool result, the rider's prompt), and any
text the model writes. The gates treat every model output as a proposal.

## Defended threats

| Threat | Where it enters | Defense | Proof | Ablation row |
|---|---|---|---|---|
| The model names a station or elevator that does not exist, in a tool call | model | `KBHook` cancels the call before the tool runs; the gateway's Cedar denies the same call in deployment | `test_two_stage_gate_corrects_every_mistake_once`, `test_cedar_and_python_hook_agree_on_random_inputs` | `without_kb_hook`: still zero leaks, because the plan gate and the hook on the `Plan` tool cover the field; the hook is what keeps a hostile tool call from executing |
| The model picks an option that is not BART's top feasible option | model | the option gate before the tool (`Guide`), then the plan gate after the model | `test_two_stage_gate_corrects_every_mistake_once` | `without_option_gate`: zero leaks; `without_plan_fields`: 20 wrong options reach the rider |
| The model invents minutes, in the field or in the sentence | model | the plan gate compares the field with the policy engine; `prose_findings` reads the sentence | `test_after_model_gate_rejects_invented_minutes_and_foreign_station`, `test_prose_attacks_are_caught_by_the_after_model_gate`, the fuzz test | `without_plan_fields`: 40 wrong minutes reach the rider; `without_after_model_gate`: 80 |
| A hostile sentence with no numbers and no codes (the kind an outage feed or a station page can inject) | feed text, page text, tool result | the rider receives only a sentence code composed from the decision and BART's own option text; the plan gate accepts nothing else | `test_gate_discards_own_words_and_injected_text`, `test_approved_sentences_are_composed_from_the_decision_and_barts_text`, `test_approval_fuzz_accepts_only_whitespace_and_trailing_punctuation_variants` (the false-accept surface is exactly whitespace and trailing punctuation) | `without_plan_approval`: 20 of 20 injected sentences reach the rider |
| The model decides by itself that a trip is affected, or not | model | affectedness is the policy engine's; a draft for an unaffected trip is Guided, a plan for one is rejected | `test_unaffected_trip_is_refused` (see `tests/test_gates.py`) | covered by `plan_fields` |
| The model never complies and the run would loop without limit | model, and the SDK's unbounded after-model retry loop | a per-run cap on model calls; at the cap code composes the plan, so the rider still gets one | `test_delivery_falls_back_to_code_when_the_model_never_complies`, `test_forced_structured_output_is_gated_and_its_failure_is_delivered` (a model that answers in prose and will not call the Plan tool even when forced), `test_upstream_note_reproduction_runs_as_written` | every configuration delivered every plan (`summary.every_config_delivered_every_plan`) |
| A gate throws (a bug, a malformed message) | our code | both steering methods catch and return `Guide`; the SDK would otherwise treat a raising handler as `Proceed` | `test_gates_fail_closed_on_internal_error`, `test_a_handler_that_raises_fails_open_in_strands` | none: a raising gate is a Guide, so its row is `all_gates` |
| The SDK does not invoke the after-model gate at all (a plumbing change in a future version) | the SDK | the delivery layer runs the same checks once more before anything reaches the rider and composes the plan in code on a mismatch | `test_delivery_rechecks_the_plan_even_if_the_gate_never_fired` | the final check honours the ablation switches, so the study still measures the gates |
| The model "decides" for the rider after dark or at the last train | model | the run pauses with an `Interrupt`; only the rider's answer resumes it; a model cannot mark a plan held | `test_run_pauses_writes_card_and_resumes_on_yes`, `test_model_cannot_hold_without_the_rider` | not part of the red team; the quiet metric counts interruptions and decisions |
| The rider is told twice about one outage (every five minutes, for hours) | our code | `SentLog` in the runtime: a plan sent for a case is not sent again while the outage lasts, and no model runs for the repeat; cleared when the elevator is back | `test_one_outage_one_message` | not part of the red team; the quiet metric counts what was sent |
| The rider is asked the same question twice, nagged while a question is open, or asked about an outage that already ended | our code | `DecisionMemory` in `agent.state`, the inbox read before a new ask, `Inbox.withdraw_stale` on every poll | `test_same_case_does_not_interrupt_again`, `test_pending_case_is_not_asked_again_on_the_next_poll`, `test_open_question_is_withdrawn_when_the_elevator_comes_back` | |
| The rider is held, or sent a plan unasked, on last month's answer: a decision remembered past its outage | our code | `DecisionMemory.clear_stale` on every poll (the mirror, the session's copy, a cleared event in Memory, a tombstone against the restored session copy) | `test_a_decision_belongs_to_its_outage`, `test_the_memory_forgets_a_decision_when_its_outage_ends_in_every_copy` | |
| The rider's note (their own free text) is read as an instruction: a plan, a station, a number, a reordering | the rider, or whoever types in their app | `RiderNote`: a fixed vocabulary, every quote checked against the note, constraints applied as feasibility only, BART's order among the rest; set aside when nothing is left | `test_the_model_may_only_point_at_the_riders_words`, `test_a_constraint_only_takes_options_away_and_barts_order_stands`, `test_over_every_case_and_every_constraint_set_a_note_only_ever_removes`, `test_the_note_is_read_by_a_fresh_agent_with_no_session` | `make runtime-sweep`: a note that only gives orders changed nothing 194 of 194 times, a note with a real constraint and orders took one option away and nothing else 194 of 194 (`results/runtime_sweep.json`, claims `runtime_sweep.note_orders`, `runtime_sweep.note_removes`) |
| A tool call reaches the gateway with hostile arguments | model, through the gateway | AgentCore Policy: Cedar generated from the frozen KB, default deny, forbid wins, validated locally against the generated schema | `test_local_cedar_evaluation_denies_fake_station_and_option`, `test_generated_policies_validate_against_the_schema` | the hook is its in-process twin (`test_cedar_and_python_hook_agree_on_random_inputs`) |
| A number in the submission text that no results file supports | us | `make check-docs` refuses a results-derived phrase that does not match `results/`; `make verify-claims` checks 84 claims; CI regenerates every results file and diffs it | `make verify` | |
| A key in the repo, a test that reaches the network or a laptop's keys | us | the secret scan over tracked files; tests patch `socket.getaddrinfo` and `socket.create_connection` to raise, strip every live key name from the environment and point the shared credentials file variable at a path that does not exist | `tests/conftest.py`, `scripts/secret_scan.py`, `test_credentials_present_sees_the_environment_and_the_shared_file_but_never_a_laptops_keys` | |

## Threats this package does not defend, and what stands in

- A wrong knowledge base. If a station page changes or a labeler erred,
  the gates enforce the wrong fact faithfully. What stands in: the KB is
  frozen at a tag, labelled by two people, and every plan carries the
  source URL so the rider and the archive can check it. A KB refresh is a
  new tag and a new red-team run.
- A wrong policy engine. Minutes and order are its; the gates only check
  that the model copied them. What stands in: the policy engine is pure
  code with the 194 frozen cases as ground truth, and the AgentCore
  evaluation dataset is exported from it, so a drift between the two shows
  up as a failing scenario.
- A lying feed. If the feed says an elevator is out when it is not, the
  rider gets a needless reroute; if it says nothing, the rider gets no
  warning. What stands in: the poller diffs snapshots into an archive at
  five-minute resolution, and the quiet metric reports every plan sent, so
  a noisy feed shows up as a noisy week.
- Two pollers for the same rider at once. One outage, one message holds
  through the sent log, which two processes on one machine share under a
  lock, and across sessions through Memory's durable copy read before a
  run; two containers polling the same rider in the same minute could
  each send once. What stands in: one poller per deployment, and the
  runtime session id per rider that the runbook prescribes, so the same
  rider's invocations queue on one session.
- The rider's saved trips are sensitive (where a person is, and when). The
  dispatch package keeps them in session state and in the evidence packets
  on disk under the owner's control; nothing leaves the process except the
  model call, which carries the trip's station codes and the outage. What
  stands in: the runtime entrypoint takes the rider id as an opaque string,
  the packets can be regenerated without timestamps, and no rider data is
  in this repository (three synthetic riders only). A rider's note is read
  once and never stored: the words go to the one model call that reads
  them and nowhere else (a fresh agent with no session), and the runtime
  keeps only the constraint kinds it produced. The retention rule for
  what the agent keeps about a rider is `make retention DAYS=30`: closed
  decision cards (answered or withdrawn) and evidence packets older than the
  rule are dropped, open cards never are, the trip's Strands session (the
  conversation with the outage's tool results) is deleted by the runtime
  as soon as nothing is out on the trip, and the decision mirrors and
  the outage archive are the owner's to rule on; the number of days is the
  owner's choice, and the default is a dry run. With AgentCore Memory as
  the durable store, the same rule is the Memory's event expiry: the
  decisions, the deliveries and the cards expire after that many days, in
  an AWS-managed store under the rider's actor id (a customer key is one
  parameter away, `encryptionKeyArn` on the plan).
- Availability. If Bedrock is down, the model call fails, and `deliver()`
  composes the plan in code (the exception path), so the rider still gets
  BART's option; the rider message will be the short default sentence. If
  the feed is down, nothing is sent, and the quiet report says so. If
  AgentCore Memory is down (a throttle, an outage, a permission error),
  no invocation fails: the stores call it through `ResilientMemoryClient`,
  which marks the durable copy degraded (the response says so, the trace
  carries `memory.degraded`), the session's own copy serves, and a write
  that failed is replayed before the next call with the same idempotency
  token, so the durable copy catches up without duplicates. What the
  outage costs: while it lasts, "never asked twice" and "one outage, one
  message" hold within the session, not across sessions.
- Prompt injection that changes which option the model picks. It cannot
  change what the rider receives (the option is the policy engine's, the
  sentence is code's), but it can cost model calls up to the cap. What
  stands in: the cap, the evidence packet that records every attempt, and
  the convergence study that shows how many calls a repair takes.
- An injection in the rider's note. The note is the rider's own text and
  goes through the model, but the model may only return constraints from
  a fixed vocabulary with the rider's words as the reason (`RiderNote`);
  a kind outside the vocabulary never parses, a quote not in the note is
  dropped, and a constraint can only mark an option infeasible. The worst
  a hostile note can do is rule out BART's first option, in which case the
  rider gets BART's next option with the policy engine's minutes; it can
  never add an option, reorder them, name a station or set a number
  (`test_the_model_may_only_point_at_the_riders_words`); the runtime
  sweep sends two such notes through the whole hosted contract for every
  case and counts it (`runtime_sweep.note_orders`,
  `runtime_sweep.note_removes`).
- A provider that rejects the conversation a retry produces. Bedrock
  requires alternating roles, and two rejections in a row leave two user
  turns; the cap wrapper folds them and places the SDK's neutral turn
  after a tool result ahead of time, so every retry is accepted at the
  first attempt by a stand-in that enforces the strict rules through the
  real adapter (`make wire`: every gate then two Guides in a row, none
  rejected; every convergence persona, both tool-result formats, none
  rejected), and a fuzz over every conversation shape Strands leaves.
  If a provider still rejects a call, `deliver()` composes the plan in
  code (the exception path). Not yet observed live.
- A provider error, a throttle, a response cut off by the token limit.
  Priced on the wire: a permission error and a truncated response cost
  one call and the rider still gets the plan (code composes it); a
  throttle is retried by the SDK's backoff, then the plan. A provider
  that fails on every call stops a live-eval entry after three errors in
  a row rather than filling it with silent disagreements.
- Two writers on the inbox. The poller writes cards while the app posts
  answers; each read-modify-write holds an advisory lock and every save is
  an atomic rename, so no answer is lost and no reader sees a torn file
  (eight threads, 320 cards, in the test). Across machines, the app's own
  store replaces the JSON file (INTEGRATION.md section 5).
- Anything the rider does after reading the plan. The plan is BART's
  published option; whether it is safe for this rider tonight is the human
  moment's question, which is why after dark and at last train the agent
  asks instead of deciding.

## What a change to the gates must do

Any change to `gates.py` or `messages.py` must keep `make verify` green,
`make red-team-exhaustive` at four zeros, and `make ablation` with the
after-model gate still load-bearing (its removal must still leak). A gate
that can be removed without a leak and without a convergence cost is a
candidate for removal, not a trophy; the two before-tool gates stay for
the reasons in their ablation rows, and that reasoning is written down so
the next person can disagree with it.
