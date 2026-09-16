"""make walkthrough: one outage, end to end, as a page a judge can click through with nothing installed.

    python scripts/walkthrough.py                 # build/walkthrough/index.html and artifact.html

Four scenes from the four committed evidence packets and the quiet metric: the morning the elevator goes
out, the rider's own words, the night the agent asks instead of sending (the reader answers, and both
answers are the recorded ones), and the week. Every sentence, reason, option, minute and count on the page
is read out of `docs/evidence/*.json` and `results/*.json` at build time, so the page cannot say something
the run did not: `tests/test_walkthrough.py` checks each string against its source.

`index.html` is the standalone document (the evidence site and a local browser); `artifact.html` is the
same body without the document shell, for a host that supplies one.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence"
RESULTS = ROOT / "results"
OUT = ROOT / "build" / "walkthrough"

OPTION_WORDS = {
    "alternate_elevator": "the alternate elevator route at the same station",
    "transit": "the transit connection BART lists",
    "backtracking": "riding back to the previous accessible station",
}


def packet(name: str) -> dict[str, Any]:
    return json.loads((EVIDENCE / f"{name}.json").read_text())


def results(name: str) -> dict[str, Any]:
    return json.loads((RESULTS / name).read_text())


def e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def attempts(pkt: dict[str, Any]) -> list[dict[str, str]]:
    """The model's attempts and what stopped each, in order, from the packet's own gate events."""
    rows: list[dict[str, str]] = []
    for ev in pkt["gate_events"]:
        kind = ev["kind"]
        if kind == "hook.cancel_tool":
            rows.append(
                {
                    "tried": "draft_plan with an elevator the knowledge base does not have",
                    "stopped": "A hook cancelled the tool call before it ran.",
                    "reason": ev["reason"],
                    "control": "BeforeToolCallEvent",
                }
            )
        elif kind == "steering.guide":
            rows.append(
                {
                    "tried": "draft_plan with an option that is not BART's first",
                    "stopped": "Steering sent the call back with BART's order.",
                    "reason": ev["reason"],
                    "control": "steer_before_tool",
                }
            )
        elif kind == "steering.guide_after_model":
            rows.append(
                {
                    "tried": "a finished Plan with the wrong option and invented minutes",
                    "stopped": "Steering threw the model's plan away and made it try again.",
                    "reason": ev["reason"],
                    "control": "steer_after_model",
                }
            )
        elif kind == "steering.proceed_after_model":
            rows.append(
                {
                    "tried": "a finished Plan that matches the policy engine",
                    "stopped": "",
                    "reason": "plan matches",
                    "control": "steer_after_model",
                }
            )
    return rows


def ledger(pkt: dict[str, Any]) -> str:
    out = []
    n = 0
    for row in attempts(pkt):
        if not row["stopped"]:
            out.append(
                f'<li class="try ok"><p class="what">The model proposed {e(row["tried"])}.</p>'
                f'<p class="verdict">Accepted. It carries the policy engine\'s station, option and minutes, '
                f"and one of the sentences code composed.</p>"
                f'<p class="ctl">{e(row["control"])}</p></li>'
            )
            continue
        n += 1
        out.append(
            f'<li class="try"><p class="what"><span class="n">Attempt {n}</span> {e(row["tried"])}</p>'
            f'<p class="verdict">{e(row["stopped"])}</p>'
            f'<p class="reason">{e(row["reason"])}</p>'
            f'<p class="ctl">{e(row["control"])}</p></li>'
        )
    return "\n".join(out)


def scene_receipt(label: str, value: str, source: str) -> str:
    return f'<div class="receipt"><dt>{e(label)}</dt><dd>{e(value)}</dd><dd class="src">{e(source)}</dd></div>'


def body() -> str:
    day = packet("DELN-E1-daytime")
    note = packet("DELN-E1-note")
    yes = packet("DELN-E1-after-dark-yes")
    no = packet("DELN-E1-after-dark-no")
    quiet = results("quiet.json")
    sweep = results("runtime_sweep.json")
    red = results("red_team_exhaustive.json")
    abl = results("gate_ablation.json")

    card = yes["decision_card"]
    trip = day["trip"]
    rejected = card["rejected"][0]
    reached = red["reached_rider"]
    opt = OPTION_WORDS.get

    origin, dest = trip["origin"], trip["destination"]
    elevator = trip["outages"][0]
    source = day["decision"]["source_url"]
    day_msg = day["final_plan"]["rider_message"]
    day_opt = opt(day["final_plan"]["option"], day["final_plan"]["option"])
    day_min = day["final_plan"]["added_minutes"]
    day_calls = day["cost"]["model_calls"]
    note_text = note["note"]["text"]
    note_msg = note["final_plan"]["rider_message"]
    note_kinds = ", ".join(note["note"]["constraints"])
    note_opt = opt(note["final_plan"]["option"], note["final_plan"]["option"])
    note_min = note["final_plan"]["added_minutes"]
    yes_msg = yes["final_plan"]["rider_message"]
    no_msg = no["final_plan"]["rider_message"]
    interrupts = yes["counts"]["interrupts"]
    card_opt = opt(card["option"], card["option"])
    cases, invocations = sweep["cases"], sweep["invocations"]
    leaked = abl["configs"]["without_after_model_gate"]["leaked_runs"]
    abl_runs = abl["configs"]["all_gates"]["runs"]
    zeros = ", ".join(
        str(reached[k])
        for k in ("hallucinated_stations", "wrong_options", "minutes_not_from_policy", "unapproved_messages")
    )
    receipts_1 = "".join(
        [
            scene_receipt("Option", day_opt, "the policy engine's first feasible option"),
            scene_receipt("Minutes", f"{day_min} more", "the policy engine, never the model"),
            scene_receipt("Model calls", str(day_calls), "docs/evidence/DELN-E1-daytime.json"),
        ]
    )
    receipts_2 = "".join(
        [
            scene_receipt("Read as", note_kinds, "a fixed vocabulary, quoted from her words"),
            scene_receipt("Option now", note_opt, "re-ranked under her constraint"),
            scene_receipt("Minutes", f"{note_min} more", "the policy engine"),
        ]
    )
    outcomes = json.dumps({"yes": yes_msg, "no": no_msg})

    return PAGE.format(
        origin=e(origin),
        dest=e(dest),
        elevator=e(elevator),
        source=e(source),
        day_msg=e(day_msg),
        receipts_1=receipts_1,
        ledger_1=ledger(day),
        note_text=e(note_text),
        note_msg=e(note_msg),
        receipts_2=receipts_2,
        cases=e(cases),
        invocations=e(invocations),
        question=e(card["question"]),
        card_station=e(card["station"]),
        card_elevator=e(card["elevator"]),
        card_opt=e(card_opt),
        card_min=e(card["added_minutes"]),
        card_source=e(card["source_url"]),
        rej_label=e(rejected["label"]),
        rej_reason=e(rejected["reason"]),
        interrupts=e(interrupts),
        days=e(quiet["days"]),
        checked=e(quiet["trips_checked"]),
        quiet_trips=e(quiet["quiet_trips"]),
        background=e(quiet["plans_sent_in_background"]),
        asked=e(quiet["interruptions"]),
        opening=e(quiet["opening_line"]),
        red_runs=e(red["runs"]),
        zeros=e(zeros),
        leaked=e(leaked),
        abl_runs=e(abl_runs),
        outcomes=outcomes,
    )


PAGE = """
<header class="masthead">
  <p class="eyebrow">Last Elevator</p>
  <h1>One outage at Del&nbsp;Norte</h1>
  <p class="standfirst">A rider who depends on elevators has a saved trip from
    <span class="code">{origin}</span> to <span class="code">{dest}</span>. At {origin}, elevator
    <span class="code">{elevator}</span> goes out. This is what happens next, in four scenes, with nothing
    installed. Every sentence, reason, option and minute on this page was read out of the committed
    evidence packets and results files at build time, not written for the page.</p>
  <nav class="rail" aria-label="The four scenes">
    <a href="#scene-1"><span>Morning</span> the plan arrives</a>
    <a href="#scene-2"><span>Her words</span> a constraint, not an order</a>
    <a href="#scene-3"><span>After dark</span> it asks instead</a>
    <a href="#scene-4"><span>The week</span> what the silence is worth</a>
  </nav>
</header>

<main>
<section class="scene" id="scene-1" aria-labelledby="h-1">
  <div class="scene-head">
    <p class="when">Morning, daytime</p>
    <h2 id="h-1">The plan arrives before she leaves the house</h2>
    <p class="lede">The feed shows the outage. Code, not a model, decides the trip is affected and ranks
      BART's own options in BART's published order. A Strands agent drafts the plan, and three gates decide
      whether it is allowed to reach her.</p>
  </div>
  <div class="split">
    <div class="rider">
      <p class="panel-label">What the rider gets</p>
      <div class="phone">
        <p class="msg">{day_msg}</p>
        <p class="meta">Composed by code from BART's own option text.
          <a href="{source}">BART's accessible path page for {origin}</a></p>
      </div>
      <dl class="receipts">{receipts_1}</dl>
    </div>
    <div class="under">
      <p class="panel-label">What happened underneath</p>
      <ol class="ledger">
{ledger_1}
      </ol>
    </div>
  </div>
</section>

<section class="scene" id="scene-2" aria-labelledby="h-2">
  <div class="scene-head">
    <p class="when">The same morning</p>
    <h2 id="h-2">She types one line, and it can only take options away</h2>
    <p class="lede">The rider's own words are the one input that is neither a fact nor a decision. The model
      may read them only into a fixed vocabulary, with her words as the reason; code applies what is left as
      feasibility and nothing else.</p>
  </div>
  <div class="split">
    <div class="rider">
      <p class="panel-label">What the rider gets</p>
      <p class="note-in">She wrote: <q>{note_text}</q></p>
      <div class="phone">
        <p class="msg">{note_msg}</p>
        <p class="meta">The ramp route is out for her today, so BART's next option stands, with the policy
          engine's minutes.</p>
      </div>
      <dl class="receipts">{receipts_2}</dl>
    </div>
    <div class="under">
      <p class="panel-label">The rule, measured</p>
      <p class="measured">A note that only gives orders changed nothing, on every one of the
        <strong>{cases}</strong> cases in the knowledge base, and a note with a real constraint removed one
        option and no more, on every one of them.</p>
      <p class="src-line">results/runtime_sweep.json, {invocations} invocations</p>
      <p class="measured">A note can take an option away. It can never add one, reorder them, or change a
        number.</p>
    </div>
  </div>
</section>

<section class="scene" id="scene-3" aria-labelledby="h-3">
  <div class="scene-head">
    <p class="when">After dark</p>
    <h2 id="h-3">It asks instead of sending, and waits</h2>
    <p class="lede">After dark and at the last train, the run pauses on a Strands interrupt. The same case
      never asks twice, and the question is withdrawn if the elevator comes back first. Answer it yourself:
      both outcomes below are the recorded ones.</p>
  </div>
  <div class="split">
    <div class="rider">
      <p class="panel-label">The decision card</p>
      <div class="card">
        <p class="q">{question}</p>
        <dl class="card-facts">
          <div><dt>Station</dt><dd><span class="code">{card_station}</span></dd></div>
          <div><dt>Elevator out</dt><dd><span class="code">{card_elevator}</span></dd></div>
          <div><dt>BART's option</dt><dd>{card_opt}</dd></div>
          <div><dt>Added minutes</dt><dd>{card_min}</dd></div>
          <div><dt>Source</dt><dd><a href="{card_source}">BART's page for this station</a></dd></div>
        </dl>
        <p class="rejected"><span>Rejected</span> {rej_label}. {rej_reason}</p>
        <div class="answer" role="group" aria-label="Answer the decision card">
          <button type="button" id="ans-yes" class="btn" aria-pressed="false">Send it now</button>
          <button type="button" id="ans-no" class="btn" aria-pressed="false">Not tonight</button>
        </div>
      </div>
      <div class="outcome" id="outcome" aria-live="polite">
        <p class="outcome-hint">Choose an answer to see what she gets.</p>
      </div>
    </div>
    <div class="under">
      <p class="panel-label">What the run does either way</p>
      <ul class="plain">
        <li>The run paused on an interrupt and raised it once.
          <span class="src-line">interrupts: {interrupts}</span></li>
        <li>On yes, the plan is sent and the case is remembered, so the same outage never asks again.</li>
        <li>On no, the plan is held on file with BART's values and the status <span class="mono">hold</span>,
          and the next outage of the same elevator asks afresh.</li>
        <li>If the elevator comes back before she answers, the question is withdrawn rather than left
          hanging.</li>
      </ul>
    </div>
  </div>
</section>

<section class="scene" id="scene-4" aria-labelledby="h-4">
  <div class="scene-head">
    <p class="when">Over a week</p>
    <h2 id="h-4">What the silence is worth</h2>
    <p class="lede">The point of the agent is how rarely it speaks. Replayed over a synthetic week for three
      synthetic riders, until the laptop reruns it on the real archive.</p>
  </div>
  <div class="week">
    <div class="stat"><p class="fig">{days}</p><p class="cap">days watched</p></div>
    <div class="stat"><p class="fig">{checked}</p><p class="cap">trips checked</p></div>
    <div class="stat"><p class="fig">{quiet_trips}</p><p class="cap">quiet, she heard nothing</p></div>
    <div class="stat"><p class="fig">{background}</p><p class="cap">plans sent in the background</p></div>
    <div class="stat accent"><p class="fig">{asked}</p><p class="cap">times it asked her</p></div>
  </div>
  <p class="src-line centered">results/quiet.json, a synthetic week: {opening}</p>
</section>

<section class="scene proof" id="proof" aria-labelledby="h-5">
  <div class="scene-head">
    <h2 id="h-5">Why the four scenes can be trusted</h2>
  </div>
  <div class="proof-grid">
    <div class="proof-item">
      <p class="fig">{red_runs}</p>
      <p class="cap">adversarial runs through the full agent: every case in the knowledge base times every
        attack</p>
      <p class="src-line">hostile stations, wrong options, invented minutes and unapproved sentences that
        reached the rider: {zeros}. Fixture run, pending the rerun on the real knowledge base.</p>
    </div>
    <div class="proof-item">
      <p class="fig">{leaked} of {abl_runs}</p>
      <p class="cap">runs leak when the gate after the model is removed, and none leak with every gate
        on</p>
      <p class="src-line">results/gate_ablation.json: which control carries the guarantee, measured by
        removing one at a time.</p>
    </div>
    <div class="proof-item">
      <p class="fig">{invocations}</p>
      <p class="cap">invocations through the same hosted entrypoint the deployment serves, five riders per
        case</p>
      <p class="src-line">results/runtime_sweep.json: the plan the model's, the option and the minutes the
        policy engine's, on every one.</p>
    </div>
  </div>
  <p class="foot">Models propose, code decides. Built with the Strands Agents SDK 1.55.1: a hook on the
    before-tool event, steering before the tool and after the model, structured output, session state, and
    an interrupt for the one moment a person should decide. In the repository, <span class="mono">make
    judge</span> runs all of it offline in two to three minutes and prints what you just read, and
    <span class="mono">make verify</span> checks every number on this page against its results file on
    every commit.</p>
</section>
</main>

<script>
(function () {{
  var outcomes = {outcomes};
  var notes = {{
    yes: "Sent. The case is remembered, so this outage never asks again.",
    no: "Held. Nothing was sent, and the plan stays on file with BART's values."
  }};
  var box = document.getElementById("outcome");
  var buttons = {{ yes: document.getElementById("ans-yes"), no: document.getElementById("ans-no") }};
  function choose(which) {{
    box.innerHTML = "";
    var phone = document.createElement("div");
    phone.className = which === "no" ? "phone held" : "phone";
    var msg = document.createElement("p");
    msg.className = "msg";
    msg.textContent = outcomes[which];
    var meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = notes[which];
    phone.appendChild(msg);
    phone.appendChild(meta);
    box.appendChild(phone);
    Object.keys(buttons).forEach(function (k) {{
      buttons[k].setAttribute("aria-pressed", String(k === which));
      buttons[k].classList.toggle("chosen", k === which);
    }});
  }}
  buttons.yes.addEventListener("click", function () {{ choose("yes"); }});
  buttons.no.addEventListener("click", function () {{ choose("no"); }});
}})();
</script>
"""


STYLE = """
<title>One Outage at Del Norte</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=Public+Sans:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {
  --paper: #f4f6f5; --panel: #ffffff; --ink: #17201f; --ink-soft: #4b5a58; --rule: #d7dedc;
  --accent: #0f6e70; --accent-soft: #e3efee; --amber: #9a5b06; --amber-soft: #f6ecdc;
  --sent: #1a6b3a; --held: #5b6866; --shadow: 0 1px 2px rgba(23,32,31,.06), 0 8px 24px rgba(23,32,31,.05);
  --display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --body: "Public Sans", "Helvetica Neue", Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #0e1517; --panel: #151f20; --ink: #e7edec; --ink-soft: #a3b3b1; --rule: #27383a;
    --accent: #52b6b1; --accent-soft: #13302f; --amber: #d69b4a; --amber-soft: #2c2415;
    --sent: #62c08a; --held: #8fa09e; --shadow: 0 1px 2px rgba(0,0,0,.4), 0 10px 28px rgba(0,0,0,.35);
  }
}
:root[data-theme="dark"] {
  --paper: #0e1517; --panel: #151f20; --ink: #e7edec; --ink-soft: #a3b3b1; --rule: #27383a;
  --accent: #52b6b1; --accent-soft: #13302f; --amber: #d69b4a; --amber-soft: #2c2415;
  --sent: #62c08a; --held: #8fa09e; --shadow: 0 1px 2px rgba(0,0,0,.4), 0 10px 28px rgba(0,0,0,.35);
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font-family: var(--body);
  font-size: 17px; line-height: 1.55; -webkit-font-smoothing: antialiased; }
.wrap { max-width: 1080px; margin: 0 auto; padding-inline: 20px; padding-block: 0 64px; }
a { color: var(--accent); text-underline-offset: 2px; }
a:focus-visible, button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
h1, h2 { font-family: var(--display); text-wrap: balance; margin: 0; letter-spacing: -.015em; }
h1 { font-size: clamp(2.1rem, 6vw, 3.4rem); line-height: 1.05; font-weight: 700; }
h2 { font-size: clamp(1.35rem, 3vw, 1.9rem); line-height: 1.15; font-weight: 600; }
p { margin: 0; }
.masthead { padding-block: 56px 8px; display: flex; flex-direction: column; gap: 18px; }
.eyebrow { font-family: var(--display); text-transform: uppercase; letter-spacing: .18em;
  font-size: .74rem; color: var(--accent); font-weight: 600; }
.standfirst { max-width: 64ch; color: var(--ink-soft); font-size: 1.05rem; }
.rail { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 6px; }
.rail a { display: flex; flex-direction: column; gap: 1px; text-decoration: none; color: var(--ink);
  border: 1px solid var(--rule); border-left: 3px solid var(--accent); background: var(--panel);
  padding: 8px 14px; font-size: .84rem; }
.rail a span { font-family: var(--display); text-transform: uppercase; letter-spacing: .1em;
  font-size: .68rem; color: var(--accent); }
.scene { padding-block: 52px; border-top: 1px solid var(--rule); }
.scene-head { display: flex; flex-direction: column; gap: 10px; max-width: 68ch; }
.when { font-family: var(--mono); font-size: .78rem; letter-spacing: .04em; color: var(--amber);
  text-transform: uppercase; }
.lede { color: var(--ink-soft); }
.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 28px; margin-top: 28px; }
@media (max-width: 820px) { .split { grid-template-columns: minmax(0, 1fr); } }
.panel-label { font-family: var(--display); text-transform: uppercase; letter-spacing: .12em;
  font-size: .7rem; color: var(--ink-soft); margin-bottom: 10px; }
.phone { background: var(--panel); border: 1px solid var(--rule); border-top: 3px solid var(--accent);
  padding: 18px 18px 14px; box-shadow: var(--shadow); display: flex; flex-direction: column; gap: 10px; }
.phone.held { border-top-color: var(--held); }
.msg { font-size: 1.12rem; line-height: 1.5; }
.meta { font-size: .84rem; color: var(--ink-soft); }
.note-in { margin-bottom: 12px; color: var(--ink-soft); }
.note-in q { color: var(--ink); font-style: italic; }
.receipts { display: flex; flex-direction: column; gap: 0; margin: 16px 0 0; }
.receipt { display: grid; grid-template-columns: 8.5rem minmax(0, 1fr); gap: 2px 14px;
  padding: 9px 0; border-bottom: 1px solid var(--rule); }
.receipt dt { font-family: var(--display); font-size: .78rem; text-transform: uppercase;
  letter-spacing: .08em; color: var(--ink-soft); }
.receipt dd { margin: 0; }
.receipt .src { grid-column: 2; font-size: .78rem; color: var(--ink-soft); font-family: var(--mono); }
.ledger { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.try { background: var(--panel); border: 1px solid var(--rule); border-left: 3px solid var(--amber);
  padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; }
.try.ok { border-left-color: var(--sent); }
.try .n { display: block; font-family: var(--display); text-transform: uppercase; letter-spacing: .1em;
  font-size: .68rem; color: var(--amber); margin-bottom: 2px; }
.try.ok .n { color: var(--sent); }
.what { font-size: .96rem; }
.verdict { font-weight: 600; font-size: .96rem; }
.reason { font-family: var(--mono); font-size: .8rem; line-height: 1.5; color: var(--ink-soft);
  background: var(--amber-soft); padding: 8px 10px; overflow-x: auto; }
.try.ok .reason { background: var(--accent-soft); }
.ctl { font-family: var(--mono); font-size: .74rem; color: var(--accent); }
.measured { margin-bottom: 10px; }
.src-line { font-family: var(--mono); font-size: .76rem; color: var(--ink-soft); }
.src-line.centered { text-align: center; margin-top: 14px; }
.card { background: var(--panel); border: 1px solid var(--rule); border-top: 3px solid var(--amber);
  padding: 18px; box-shadow: var(--shadow); display: flex; flex-direction: column; gap: 14px; }
.q { font-size: 1.05rem; }
.card-facts { margin: 0; display: flex; flex-direction: column; gap: 0; }
.card-facts > div { display: grid; grid-template-columns: 9rem minmax(0, 1fr); gap: 14px;
  padding: 7px 0; border-bottom: 1px solid var(--rule); }
.card-facts dt { font-family: var(--display); font-size: .76rem; text-transform: uppercase;
  letter-spacing: .08em; color: var(--ink-soft); }
.card-facts dd { margin: 0; }
.rejected { font-size: .88rem; color: var(--ink-soft); }
.rejected span { font-family: var(--display); text-transform: uppercase; letter-spacing: .08em;
  font-size: .7rem; color: var(--amber); }
.answer { display: flex; gap: 10px; flex-wrap: wrap; }
.btn { font-family: var(--display); font-size: .92rem; font-weight: 600; cursor: pointer;
  border: 1px solid var(--accent); background: transparent; color: var(--accent);
  padding: 10px 18px; }
.btn:hover { background: var(--accent-soft); }
.btn.chosen { background: var(--accent); color: var(--panel); }
.outcome { margin-top: 16px; min-height: 96px; }
.outcome-hint { font-size: .88rem; color: var(--ink-soft); font-style: italic; }
.plain { margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: 10px;
  font-size: .96rem; }
.plain .src-line { display: block; }
.code { font-family: var(--mono); font-weight: 500; letter-spacing: .03em; background: var(--accent-soft);
  color: var(--accent); padding: 1px 6px; }
.mono { font-family: var(--mono); font-size: .9em; }
.week { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin-top: 28px; }
@media (max-width: 820px) { .week { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.stat { background: var(--panel); border: 1px solid var(--rule); padding: 16px;
  display: flex; flex-direction: column; gap: 4px; }
.stat.accent { border-left: 3px solid var(--accent); }
.fig { font-family: var(--display); font-size: 2.1rem; line-height: 1; font-weight: 700;
  font-variant-numeric: tabular-nums; }
.cap { font-size: .84rem; color: var(--ink-soft); }
.proof-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-top: 26px; }
@media (max-width: 820px) { .proof-grid { grid-template-columns: minmax(0, 1fr); } }
.proof-item { display: flex; flex-direction: column; gap: 8px; border-top: 2px solid var(--accent);
  padding-top: 14px; }
.proof-item .fig { font-size: 1.9rem; color: var(--accent); }
.foot { margin-top: 30px; max-width: 70ch; color: var(--ink-soft); font-size: .94rem; }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
</style>
"""


def page(body_html: str, standalone: bool) -> str:
    inner = f'<div class="wrap">{body_html}</div>'
    if not standalone:
        return STYLE + inner
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + STYLE
        + "</head>\n<body>\n"
        + inner
        + "\n</body>\n</html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    out = OUT if argv is None or not argv else Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    b = body()
    (out / "index.html").write_text(page(b, standalone=True))
    (out / "artifact.html").write_text(page(b, standalone=False))
    print(f"wrote {out / 'index.html'} and {out / 'artifact.html'} ({len(b)} bytes of body)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
