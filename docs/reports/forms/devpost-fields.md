# The Devpost form, field by field (prepared Sunday 05:00 PDT; the browser extension was not connected)

The built-in browser could not reach Chrome from the dispatch session (the extension reported not
connected), so no form was filled or screenshotted; this sheet is the fill, ready to paste, and the list
of what waits on the owner. When the browser is connected, the same sheet is what gets typed in, field
by field, stopping before Submit. Every value below is from `docs/devpost.md`, `README.md` and
`docs/SUBMISSION-CHECKLIST.md`; nothing is typed from memory.

## Fields ready to paste

| Field | Value | Source |
|---|---|---|
| Project name | Last Elevator | `README.md` |
| Tagline (elevator pitch) | If the field allows 120 characters: "Warns, reroutes and informs a BART rider who depends on elevators, in BART's own words. Models propose, code decides." (117). If it caps at 60: "BART elevator outages, handled for the rider who needs them" (59). | `docs/README-sections.md` (the TL;DR and the rule); the form's own limit decides which |
| Track | Everyday Agents | `docs/devpost.md` line 3 |
| Description | the body of `docs/devpost.md` from "## Inspiration" through "## What's next for Last Elevator", then "## Screenshots" | `docs/devpost.md` |
| Built With | strands-agents, amazon-bedrock, amazon-bedrock-agentcore, python, sqlite, fastmcp, opentelemetry | `docs/devpost.md` line 3 |
| Architecture diagram | `docs/screenshots/06-architecture.png` (upload) | `make screenshots` |
| Gallery images | `docs/screenshots/00-first-shot.gif` first (the still `00-first-shot.png` if the form refuses a GIF), then `01` to `07` and `09`, in order; `08-axe.png` and the app's own screen from the laptop | `docs/screenshots/README.md` |
| Testing instructions | "Offline, no keys: `python3 -m venv .venv && . .venv/bin/activate && make install && make demo-one` (one rider, one outage, every gate fires); `make judge` for the whole tour in two to three minutes; `docs/TOUR-TRANSCRIPT.md` is what it prints; `docs/FAQ.md` answers the questions a judge asks with what proves each; `pip install -e '.[aws]' && make serve` starts the same AgentCore Runtime app the deployment serves, on this machine on a stand-in model, and prints a curl line per state. Live: the URL in the Links section." | `README.md` "For judges" and "Setup a stranger could run cold" |
| Disclosure | "All code was written between August 10 and September 14, 2026 with AI coding assistants. Pre-existing code: none." (the owner confirms the last clause) | `docs/devpost.md` "Disclosure" |

## Fields that wait on the owner

| Field | Why | When |
|---|---|---|
| Public repo URL | the repository is private until the owner flips it and the About panel shows the license | tonight, after the merge |
| Video URL | the cut is tonight; the URL must be public and under five minutes | tonight |
| Live URL | the app's deployment (the laptop's block 3); until then the evidence site URL from GitHub Pages | Sunday afternoon |
| Builder ID email | the owner's own | at the form |
| builder.aws post URLs (three) | published by the owner from `docs/posts/publish-ready/` | tonight and Monday morning |
| The last "TODO confirm" in the disclosure | the owner's statement | at the form |
| Submit | OWNER-CLICK | Monday before noon |

## Screenshots of the filled form

None yet: `docs/reports/forms/` gets one screenshot per form once the browser is connected and the owner
has logged in (the login is the owner's click; the filling is the session's; Submit is the owner's).
