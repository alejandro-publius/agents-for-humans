# Rubric self-score (dispatch session, Sunday 03:00 PDT, revised 07:00 PDT, before the laptop's live runs)

Scored against the Agents for Humans rubric as the work order states it: Technical Implementation (Strands
depth, live demo, AgentCore), Design (a complete product), Potential Impact (credible, specific,
demonstrated), Creativity (non-obvious Strands, problem understanding), Presentation (end to end on video;
the problem, who, why). Ties break on Technical Implementation. Every point claimed has its evidence
next to it: a file, a command, or a numbered screenshot in `docs/screenshots/`. Two scores per criterion:
now, and after the Sunday laptop runs in `docs/SUNDAY.md` land (the second is what the judges will see if
the plan holds; it is not a result until then).

## Technical Implementation: 7 now, 9 after the live runs

Claimed and shown:

- Strands depth. Six guarantees enforced by the SDK's own surfaces, not prompts: a `BeforeToolCallEvent`
  hook that cancels a call naming a station or elevator the knowledge base does not have, a steering
  handler before the tool (`Guide`) for BART's published option order, a steering handler after the model
  that discards a plan whose station, option, minutes or sentence are not the policy engine's, structured
  output for the plan, an `Interrupt` for the human moment, session managers for the pause across
  processes, `ModelRetryStrategy` bounded on the live path. The table with one row per guarantee, the
  Strands API, the file and the test: `docs/README-sections.md` ("Strands surface used"); the evidence map
  with span events, results files and claim ids: `docs/EVIDENCE.md`. Screenshot 03 (the trace) shows all
  three gates firing on one run; `make demo-one-trace` prints it.
- Measured, not asserted. The red team (`make red-team`, screenshot 05; `results/red_team.json`), the
  exhaustive red team over every case (`results/red_team_exhaustive.json`), the ablation that says which
  gate does the work (`make ablation`, `results/gate_ablation.json`, `docs/TOUR-TRANSCRIPT.md` section 4),
  the convergence study (`results/adaptive_convergence.json`), the same personas through the real Bedrock
  adapter in both tool-result formats (`results/wire_convergence.json`), the hosted contract over the whole
  dataset (`make runtime-sweep`, `results/runtime_sweep.json`). Every number in the README is one of the
  84 claims checked by CI (`make verify-claims`, screenshot 07).
- The live path run before it runs live: the agent through Strands' real `BedrockModel` with a stand-in
  client that enforces the Converse rules; the request on file (`docs/evidence/bedrock-request.json`), a
  permission error, a throttle, a truncated response and a hung stream each priced
  (`docs/evidence/bedrock-wire.md`); one retry layer, bounded (`le_dispatch/live.py`, `make preflight`).
- Five findings about the SDK, each with an offline reproduction that runs as a test
  (`docs/UPSTREAM-NOTE.md`, `tests/test_upstream_note.py`).
- AgentCore, five surfaces, each with its calls validated against the service model before the first
  apply (`make preflight`, `le_dispatch/api_shapes.py`): Runtime (`infra/agentcore/runtime/entrypoint.py`,
  the contract served by the real SDK app in an in-process test, every state on `make demo-runtime`,
  screenshot-free but in `docs/TOUR-TRANSCRIPT.md` section 6), Policy (Cedar generated from the frozen
  knowledge base, `infra/agentcore/policy/`), Evaluations (the 194-scenario dataset, screenshot 09; the
  custom evaluator proven on real Strands spans, `evals/`), Memory (`le_dispatch/agentcore_memory.py`,
  best effort with replay), Observability (`setup_observability` in the entrypoint).

Not yet shown, and what it costs:

- No live model run. Every live row says "pending" and every results file says `claimable: false`.
  This is the largest single gap in the whole submission and it is the laptop's first hour
  (`docs/SUNDAY.md` block 2: `make demo-live DEMO_LIVE_ARGS=--yes`, then `make eval-live
  EVAL_LIVE_ARGS="--yes --limit-cases 40"`).
- No deployed AgentCore resource yet (Runtime, Policy, Memory, the Evaluations run): block 3.

Since 03:00 (F71 to F80), on this criterion: the workflow the main repo receives was run step by step in
the integrated layout and is green there (`make integrate-ci`, `docs/reports/integrated-ci.md`), after
it caught a stale badge, three targets that needed the package's history and a masked pipe; every
target the package adds is one file the main Makefile includes (`dispatch.mk`); the evidence site is
audited with axe-core on every push and on publish (`make site-a11y`, zero violations, a claim). None
of it is a live run; the score stays 7 until the laptop's first hour. Later in the morning (F89) the
hostile note went through the whole hosted contract for every case and was counted: orders in the note
change nothing 194 of 194 times, a real constraint removes one option and no more 194 of 194.

## Design (a complete product): 7 now, 8 after

Claimed and shown:

- A rider-shaped product, not a chat: a saved trip, a poller that decides in code whether the trip is
  affected and how (cannot enter, cannot exit, a transfer), a plan in BART's own words with the added
  minutes from the policy engine, a decision card after dark or at the last train, one message per outage,
  a question that never outlives its outage and a decision that never outlives its outage either
  (`docs/README-sections.md` "The human moment", screenshot 01, `make demo-runtime` for the whole state
  machine, `docs/ARCHITECTURE.md` for the two diagrams, screenshot 06).
- The rider hears plain words a screen reader can say: station names rather than codes, "at your starting
  station" rather than a label, a 160-character sentence (`le_dispatch/messages.py`,
  `tests/test_messages.py`, the read-aloud check over every case).
- What the agent keeps about a rider and for how long: a retention rule, an inbox that is locked, a session
  deleted when the outage ends, Memory events that expire (`docs/THREAT-MODEL.md` "Privacy").
- What it costs the rider's attention: the weekly quiet report (`make report`, screenshot 02).

Not yet shown:

- The rider app's own screens and the poller live in the main repo; only the card rendered from the demo's
  data is here (screenshot 01 says so). The app screenshot and the axe result (08) are the laptop's.
- The quiet week is synthetic until the archive replay (block 1).

## Potential Impact (credible, specific, demonstrated): 6 now, 8 after

Claimed and shown:

- Specific: a BART rider who depends on elevators, the outage feed, BART's published order of options,
  the July 2026 MTA settlement as the frame for what an agency now owes every rider (`docs/devpost.md`
  "Inspiration", `docs/narrative.md`); the text does not claim that Last Elevator satisfies the settlement or
  the ADA (`make check-docs` refuses such a sentence).
- Credible: the policy is the agency's own, the sentences are the agency's own wording, the model never
  decides what the rider is told (`docs/EVIDENCE.md`); any agency with an elevator feed and a published
  policy runs through every stage unchanged (`docs/ONBOARDING-AN-AGENCY.md`, `le_dispatch/portability.py`).

Not yet shown:

- Demonstrated with real riders and real outages: the real-user count in the README is TODO, the archive
  replay has not run, no live number exists. Blocks 1 and 4 in `docs/SUNDAY.md`.

## Creativity (non-obvious Strands, problem understanding): 8 now, 8 after

Claimed and shown:

- The gates are the product: steering handlers used as guarantees rather than as style, an `Interrupt`
  keyed to a policy flag rather than to a model's request, the decision (not the conversation) as the unit
  of memory, the durable copy best effort and the delivery never (`docs/README-sections.md`,
  `docs/UPSTREAM-NOTE.md`).
- The live path made offline: a stand-in client under the SDK's real adapter, a learner stand-in that reads
  the conversation and found real bugs the scripted models could not (`docs/README-sections.md` live-path
  paragraph, `docs/evidence/bedrock-wire.md`).
- Problem understanding in the details the rider meets: the morning after an unanswered night question,
  the double tap, the elevator that comes back and goes out again, the sentence that says where the outage
  bites (`README.md` rows F51, F54, F59).

## Presentation (end to end on video; the problem, who, why): 5 at 03:00, 7 on the page now, 8 after the video

Claimed and shown:

- The script with its honesty checks (`docs/video-script.md`), the exact command behind every on-screen
  moment with the lines to freeze on, verified (`docs/video/commands.md`), the two renders
  (`docs/video/trace.png`, `docs/video/eval_table.png`), nine numbered screenshots with captions
  (`docs/screenshots/README.md`, referenced by number in `docs/devpost.md`).
- A judge who reads instead of runs: `docs/TOUR-TRANSCRIPT.md` (seven sections, regenerated and diffed in
  CI), `docs/EVIDENCE.md`, `docs/THREAT-MODEL.md`; a judge who runs: `make judge`, two to three minutes; a
  stranger who starts cold: `docs/reports/cold-start.md`.

Since 03:00 (F71 to F80): the README, the sections the owner merges and the devpost open with the person,
the guarantee, the number and the human moment; the first shot is a GIF under that paragraph and the text
of the same run on the evidence site's front page (`make first-shot`, screenshot 00); the README puts the
five-minute path and the cold setup before the index; the voice-over is 85 lines of under twelve words;
every post is under 900 words; `docs/FAQ.md` answers the questions a judge asks with what proves each.
Presentation on the page is now 7; the video decides the rest.

Not yet shown:

- The video does not exist yet (tonight's cut); the devpost still carries TODO links and the disclosure
  line waits on the owner.

## The top five gaps, ranked by score gained per hour

| # | Gap | Score gained | Hours | Per hour | Whose | Where it goes |
|---|---|---|---|---|---|---|
| 1 | The first live run: `make demo-live DEMO_LIVE_ARGS=--yes` then `make eval-live EVAL_LIVE_ARGS="--yes --limit-cases 40"`, the packet and the table with live rows | +2 Technical, +1 Presentation (the live shot) | 1 | 3.0 | the laptop | `bundles/FINAL-INTEGRATION.md`, `docs/HUMAN-CHECKLIST.md` |
| 2 | The archive replay for the quiet report and the real-user count | +2 Impact | 1 | 2.0 | the laptop | `bundles/FINAL-INTEGRATION.md` |
| 3 | The video, cut from the verified commands and the station footage | +3 Presentation | 3 | 1.0 | the owner | `docs/HUMAN-CHECKLIST.md` |
| 4 | The first paragraph of the README and of the devpost: the person, the guarantee, the number, the human moment | +1 Presentation, +0.5 Impact | 0.5 | 3.0 (documents, after 6:00 PM by the work order) | this session | H7 |
| 5 | `make demo-one-brief`: the first on-screen shot as a few plain lines (what code decided, what the model tried, what stopped it, what reached the rider) instead of a JSON dump followed by the events | +0.5 Presentation | 0.5 | 1.0 | this session, code, visible in the video | implemented today (F65) |

Implemented from this list by 07:00: 5 (F65) and 4 (F75, brought forward so the owner has the text before
the cut), plus what the list did not have and the chain check found (F72, F73). Gaps 1 to 3 are the
laptop's and the owner's and are written into the integration package and the human checklist.

Added in the afternoon, from walking Sunday's checklist step by step against every rule and every CI
step (F96 to F98, all before the 6:00 PM code stop): the merge-day rehearsal's own red (a compiled test
file the scratch main repo listed), six docs rules that would have failed the moment the owner filled a
link, cited the enforced live row (which says 100 by construction), or published a post, and the CI determinism check that would have
compared the laptop's real numbers with fixture ones after the merge (the workflow now reads the
committed exports, the tests always read the fixtures, and a fixture run never overwrites a results file
a real run wrote). None of these adds a point on its own; each removes a red badge a judge could have
met on the first page.

## Blocked, and what stands in (for the main repo's day-1.md)

- H6, the browser chores (the Devpost form filled up to Submit, the builder.aws drafts, screenshots of
  the forms into `docs/reports/forms/`): the Chrome extension was not connected to the dispatch session
  at any point on Sunday, and the logins are the owner's. What stands in: the Devpost form field by
  field with what waits on the owner (`docs/reports/forms/devpost-fields.md`), the three posts as
  paste-ready text with their word counts (`docs/posts/publish-ready/`), the field survey
  (`docs/reports/field.md`), and the owner's click-by-click checklist with times
  (`docs/HUMAN-CHECKLIST.md`).
- The live runs, the archive replay and the deployment: the laptop's, by the standing rules; every
  results file says `claimable: false` until they run, and `make check-docs` keeps the words in step.

## Deliberately not built (for the main repo's day-1.md)

- A second real agency: the harness is agency-agnostic (a synthetic one runs through every stage), and a
  real one needs a station KB, two labelers and a feed parser; not this week.
- An MCP server as a feature, Strands skills packaging, a UI beyond what the video needs: the scrap list of
  the original work order stands.
- A retry queue for the poller across containers: the Memory client's backlog replays within a container;
  a lost container loses at most one poll's writes, and the next poll rewrites them.
- Concurrency control between two pollers for the same rider: not needed with one poller; listed in
  `docs/THREAT-MODEL.md` among the threats this package does not defend, with what stands in.

## What the field says

Surveyed in `docs/reports/field.md`: the Agents for Humans posts found on builder.aws.com are a
cost-control agent and a ledger agent with a pause; nothing on transit or accessibility, nothing that
measures its guarantees, so the framing stands (the person, the guarantee, the number, the human moment).
