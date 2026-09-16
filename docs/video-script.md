# Video script (under five minutes; a pitch, not a tutorial)

Shot list assumes the Saturday footage at a BART station plus screen
recordings of `make tour` (every gate, the human moment, the counts in
one run), `make ablation` (which gate protects what), `make demo-live`
on the laptop (a real model through the same gates) and the rider app
inbox. Strands must be impossible to miss: say it, show it in the code,
show the Built With tag.

## 0:00 to 0:10, headline number over the station elevator

Every voice line is under twelve words: one breath, one fact.

```
VO: Two of every hundred elevators are out right now.
VO: That is BART's own goal: ninety-eight percent.
VO: If you use a wheelchair, that elevator is your station.
```

On screen: the elevator, then the status feed. Lower third: "Last
Elevator. Built with Strands Agents SDK."

## 0:10 to 0:40, the person and the context

```
VO: A rider who depends on elevators checks the alerts.
VO: Then plans the same trip again. Every day.
VO: In July, New York's MTA settled a nine-year class action.
VO: Over exactly this.
VO: The settlement requires accessible travel information at every elevator.
VO: Platform announcements every fifteen minutes.
VO: Real-time outage information in the app.
VO: One plaintiff put it simply.
VO: You check the app before you leave. It is not updated.
VO: Last Elevator does for one rider what that now requires.
VO: Warn, reroute, inform, in real time.
VO: Using the agency's own published policy.
```

## 0:40 to 1:20, what it does, in the background

Screen: the poller diffing the feed, the saved trip, the plan arriving.

```
VO: It watches BART's elevator feed every five minutes.
VO: Code, not a model, decides whether your trip is affected.
VO: Cannot enter at your origin. Cannot exit at your destination.
VO: Or a transfer.
VO: Code ranks BART's own options in BART's published order.
VO: Alternate elevator. Backtracking. Transit.
VO: A Strands agent writes the plan and the message.
VO: You hear nothing unless your trip is affected.
```

## 1:20 to 2:45, the guarantees, shown live

Screen: `make demo-one-brief` (the run in plain lines: what code decided,
what the model tried, what stopped it, what reached the rider), then
`make demo-one-trace` for the same run as the SDK saw it. Point at each
line as it appears.

```
VO: Here is the agent misbehaving on purpose.
VO: It names an elevator that does not exist.
VO: A Strands hook cancels the call before the tool runs.
VO: It picks the wrong option.
VO: A Strands steering handler guides it back to BART's order.
VO: It writes the wrong option and invented minutes into the plan.
VO: A second gate, after the model, throws the response away.
VO: The model tries again.
VO: The plan that reaches the rider carries the knowledge base's station.
VO: BART's option. The policy engine's minutes.
VO: The sentence itself is one code composed from BART's wording.
VO: The model only picked it.
VO: Models propose. Code decides.
```

Screen: the red-team counts.

```
VO: One hundred forty adversarial runs.
VO: Fake stations. Wrong options. Invented minutes.
VO: The same tricks hidden in the rider's sentence.
VO: A hostile sentence injected through the feed.
VO: A model that never complies.
VO: Reached the rider: zero, zero, zero, zero.
VO: Every run still delivered a plan.
VO: Then every case times every attack: 2716 runs.
VO: Same zeros.
```

(If the laptop rerun is not done, say "in our fixture run" and show the
provenance line.)

Screen: the `make ablation` table, one second per row.

```
VO: We know which gate does the work.
VO: We removed them one at a time.
VO: Without the gate after the model, 120 of 140 runs leak.
VO: Without the approved-sentence check, every injected sentence gets through.
VO: Every configuration still delivered a plan.
```

Screen: `make demo-live` on the laptop, the evidence packet scrolling.

```
VO: Same gates. Real model.
```

(Only if the laptop run is done; otherwise cut this shot, never simulate
it.)

Screen (optional, ten seconds, if the live shot is cut): the `make wire`
table, `docs/evidence/bedrock-wire.md`.

```
VO: Before the first live call, we ran the live path offline.
VO: Through Strands' real Bedrock adapter, with a stand-in client.
VO: The exact request on file.
VO: Every retry accepted at the first attempt.
VO: A permission error priced at one call.
```

(Say "stand-in" on screen; it is plumbing proof, not a model result.)

## 2:45 to 3:30, the human moment

Screen: `make demo-one-after-dark`, then the inbox card in the app.

```
VO: After dark, or at the last train, it asks you.
VO: The run pauses with a Strands Interrupt.
VO: You get a card, in words a screen reader can say.
VO: BART's option. The minutes. The source page.
VO: The options it rejected, with reasons.
VO: You tap yes. The run resumes.
VO: It remembers. The same case never asks twice.
VO: If the elevator comes back first, the question is withdrawn.
VO: Not left hanging.
VO: The quiet report for a synthetic week reads:
VO: 7 days, 2 interruptions, 2 decisions.
```

Screen (ten seconds): `make demo-one-brief DEMO_ONE_ARGS='--note "No ramps
today, I am pushing a stroller"'`.

```
VO: Tell it, in your own words, what you cannot do today.
VO: The model reads the note.
VO: All it may return is a constraint from a fixed list.
VO: With your words as the reason.
VO: Code applies it: the ramp route is out for you today.
VO: BART's next option goes, with BART's minutes.
VO: A note can take options away.
VO: It can never add one, reorder them, or change a number.
VO: A note that tries to give orders changes nothing.
VO: Every case, with orders in the note: nothing changed.
```

(The last line is `make runtime-sweep`: 194 of 194, `results/runtime_sweep.json`; say "fixture run" if the
laptop has not rerun it.)

## 3:30 to 4:05, the evidence and the architecture

Screen: the architecture diagram; the policy-agreement table.

```
VO: Every number in the README is checked by CI.
VO: Two models, enforced and without steering.
VO: The gates carry the guarantee, not the model.
VO: Cedar policies for AgentCore Policy, generated from the frozen knowledge base.
VO: A 194-case ground-truth dataset feeds AgentCore Evaluations.
```

(Show "pending run" labels honestly if the laptop has not run them.)

## 4:05 to 4:35, close

Station footage.

```
VO: Last Elevator.
VO: BART today.
VO: Any agency with an elevator feed and a published policy tomorrow.
VO: Built with Strands Agents SDK, on AWS.
```

End card: repo URL, license, Built With Strands.

## The commands, verified

`docs/video/storyboard.md` (generated by `make video-assets`) is this script as one page for the cut: each
section's voice lines with the screen moments placed under their time, the command and the first line to
freeze on. `docs/video/commands.md` (the same target) has the exact command for every on-screen
moment above, the lines to freeze on as they were printed, and the whole observed output; `docs/video/trace.png`
and `docs/video/eval_table.png` are the two renders for the cut. Rerun it on the laptop after the live
runs so the eval table carries the live rows.

## Honesty checks before export

- No number on screen that is not in `results/` or marked pending.
- Never say Last Elevator satisfies the settlement or the ADA.
- Strands named at least three times and shown in code once.
- The ablation numbers on screen are the ones in `results/gate_ablation.json`
  at the commit being shown; say "fixture run" if the laptop has not rerun it.
- No live-model shot unless `docs/evidence/live-*.md` exists in the repo.
- The wire shot, if used, says "stand-in" on screen and never stands in
  for the live shot.
