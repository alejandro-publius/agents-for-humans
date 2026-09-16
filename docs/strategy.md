# Last Elevator. Strategy and build plan

Written Fri Sept 11, 2026, 2:30am PDT. Replaces Phase 1 and Phase 2 for the chosen idea. Facts carry URLs. Inferences are marked.

## 0. Verdict on the three candidates

| Idea | Live public data | Ground truth for a number | Recurring chore | Existing product to beat | Risk | Verdict |
|---|---|---|---|---|---|---|
| Last Elevator (BART) | Yes. BART API returns elevator outages, advisories, real-time departures, and trip plans; BART publishes station-specific outage options and accessible pathways for every station. https://api.bart.gov/docs/bsa/elev.aspx https://www.bart.gov/guide/accessibility/elevators | Yes. BART's own documented outage options for 14 stations are labels the agent must reproduce, and a weekend of live outages can be hand-labeled for trip relevance. | Daily. Elevator-dependent riders check before every trip. | BART app pushes elevator alerts by station and time window, but does not plan the trip around the outage. https://www.bart.gov/schedules/advisories | BART API is best-effort with no published rate limit; feed may be quiet on the demo weekend, so a replay mode is required. | Build this. |
| Evac Buddy | Partial. CAL FIRE incidents and NWS alerts are public; Genasys zone status is served through the Genasys site and app, with only scattered county ArcGIS feeds and no documented public API. https://help.genasys.com/articles/finding-your-evacuation-zone-information | Weak. Historical zone-status changes are not published as data. | Rare. Evacuations are not a weekly chore, which fights the hackathon theme. | Watch Duty and Genasys Protect already do the alerting. | Safety-critical false negatives, data-access uncertainty, nothing to demo unless a fire is burning. | Drop. |
| Rent Check | Yes. Rent Board publishes the AGA (1.0 percent for 2026), a calculator, and a public unit lookup with rent ceilings. https://rentboard.berkeleyca.gov/rights-responsibilities/rent-levels/annual-general-adjustment https://rentboard.berkeleyca.gov/services/unit-information-lookup | Partial. Ceilings are public, petition outcomes are not. | Annual. One notice a year is not a background agent. | The Rent Board's own calculator and lookup cover the arithmetic. | Berkeley-only audience, legal-advice framing, low frequency. | Keep as a blog-post anecdote, not the entry. |

Why Last Elevator clears the bar. It has every property the 2025 winners had (real data, a real place, a number, a user the builder knows) and every property the organizers asked for (background, judgment, quiet until a decision, end to end), and none of the sixteen visible entrants is near it.

## 1. The pitch

One sentence a judge repeats. Last Elevator watches BART's elevator feed for the trips you actually take, applies BART's own outage rules to your route, and interrupts you only when your trip is broken, with the exact workaround and the Mitigation Trip request already drafted.

Who it is for. Riders who cannot use stairs or escalators. Wheelchair and scooter users, people with strollers, people with injuries, seniors. BART has said the system is meant to be fully accessible and settled a disability class action over elevator and escalator failures with a requirement to dispatch repairs within one hour. https://www.cbsnews.com/sanfrancisco/news/bart-ada-lawsuit-settlement-elevator-escalator-improve-access/ The same problem produced a New York MTA settlement on July 29, 2026 that requires outage notifications and on-board announcements. https://dralegal.org/press/ny-subway-elevators-settlement/

Why now, and why here. Berkeley is where the independent living movement started, the Ed Roberts Campus sits on Ashby station, and the builder rides the same line. INFERENCE that judges will feel this, but the facts are checkable.

Why it needs an agent, in one sentence for Ifeanyi. The outage feed is free text ("DELN: Platform - Richmond"), the fix depends on where you are going and when, and BART's own policy is a ranked decision tree with judgment calls (after dark, bad weather, last train, excessive transit time), so a script can alert but cannot decide.

Track. Everyday Agents. The primary user is a rider managing their own trip. Everyday is the crowded track, and the idea is strong enough to enter it anyway. INFERENCE.

## 2. Criterion by criterion

| Criterion | What the entry shows | Artifact |
|---|---|---|
| Technical Implementation | A Strands Agent with three narrow tools, a steering handler that enforces BART's option order, BeforeToolCall hooks that reject any station or elevator name not present in the feed or the pathway data, structured output for the plan, session state per rider, deployed on AgentCore Runtime with a public status page. | Repo, AgentCore ARN, public URL, README table. |
| Design | A rider registers trips once (origin, destination, days, window, needs). After that the product is silence, an occasional message with a workaround, and a weekly line "no outages touched your trips." A public status page shows live outages and a replay for judges. | Live page, SMS or email transcript in the video. |
| Potential Impact | Riders who depend on elevators, a documented ADA issue with a settlement, a national analogue two months old, real outages on real days. | Numbers in Section 5, both settlement links. |
| Creativity and Originality | Nobody has encoded BART's published outage options into an agent that plans the workaround. The non-obvious Strands use is steering as a policy layer that mirrors BART's own ranked options. | Steering handler file, policy doc with citations. |
| Presentation | Opens with the interruption number, shows a real outage from the weekend flowing to a real plan, closes with what is simulated. | docs/VIDEO.md. |
| Bonus | Three Builder Center posts. | Section 8. |

## 3. Data, all public

- Elevator outages, live. https://api.bart.gov/api/bsa.aspx?cmd=elev&key=KEY&json=y (docs https://api.bart.gov/docs/bsa/elev.aspx). Free key by registration. https://api.bart.gov
- Service advisories, live. cmd=bsa on the same endpoint. https://api.bart.gov/docs/bsa/bsa.aspx
- Real-time departures. etd.aspx per station. Trip planning and schedules. sched.aspx. Station list. stn.aspx. https://api.bart.gov/docs/overview//examples.aspx
- GTFS and GTFS-RT feeds, which BART says are the supported standard. https://api.bart.gov
- Outage policy. Alternate elevator, then backtracking, then transit, then Mitigation Trip, then Mitigation Shuttle, with the listed Mitigation Trip justifications (no bus, after dark, bad weather, last train, unsafe waiting area, end of line). https://www.bart.gov/guide/accessibility/elevators
- Station-specific outage options for 14 stations and accessible pathways for 36 stations, linked from the same page. These become the knowledge base and the labels.
- Sunset times for the after-dark rule, and NWS alerts for the bad-weather rule. Compute sunset locally; NWS API at api.weather.gov. UNVERIFIED until fetched in the build.
- Historical outage uptime for a bigger label set if the weekend is quiet. https://www.elevatoruptime.com/city/san-francisco UNVERIFIED as to license and coverage.

## 4. Architecture and the decision boundary

```
BART feeds ──poll every 5 min (AgentCore scheduled invoke or EventBridge)──▶ Outage Diff (code)
                                                                                   │ new or changed outage
                                                                                   ▼
Rider profiles (session store) ──▶ Trip Matcher (code): does this station appear on any registered trip, in window?
                                                                                   │ yes
                                                                                   ▼
                                     Strands Agent (model) with tools:
                                       1. get_station_facts(station)  → pathways + documented outage options (local KB)
                                       2. plan_alternatives(trip, outage) → BART sched.aspx + backtracking candidates (code computes times)
                                       3. draft_message(plan)           → structured output {affected, option, steps, added_minutes, mitigation_justification}
                                     Steering handler: option chosen must be the highest-ranked feasible option in BART's order, or the message is rewritten
                                     BeforeToolCall hook: any station or elevator not in feed or KB → tool call cancelled
                                                                                   │
                                                                                   ▼
                                     Verify (code): steps reference real stations, added_minutes computed not stated, after-dark flag matches sunset
                                                                                   │
                                                                                   ▼
                                     Notify (SNS SMS or email) + status page + audit row
```

What the model decides. Whether a free-text outage actually blocks this rider's boarding, transfer, or exit. Which of the feasible options fits the rider's stated needs. How to phrase the steps.
What code decides. Trip matching, time windows, option feasibility from pathway data, minutes added, after-dark and weather flags, whether a message is sent at all.
What the rider decides. Whether to take the workaround, leave earlier, or request a Mitigation Trip. The agent drafts the request; the rider makes the call to the Station Agent or white call box, because BART requires the rider to inform staff.

## 5. Proof set

| Number | How it is produced | Where it lives |
|---|---|---|
| Policy agreement. Percent of BART's documented outage options (14 stations) that the agent reproduces from pathway data alone. Target 100 percent, and the gate fails the build below it. | evals/policy_agreement.py replays each documented outage; Strands Evals case per station; labels are BART's own text. | results/policy_agreement.json, README row 4. |
| Interruption ratio. On the weekend's live outages, messages BART-style station alerts would have sent to the rider set versus messages Last Elevator sent, with every sent message hand-labeled relevant or not. | Poll and archive the feed Fri to Sun; replay through both paths. | results/interruptions.json, opens the video. |
| Relevance precision and recall on hand-labeled live outages. | Same archive, human labels committed. | results/relevance.json. |
| Ablation. Same run with the steering handler removed. Count option-order violations and ungrounded station names. | evals/ablation.py | results/ablation.json, README limitations. |
| Cost and latency per decision, by model (Nova Lite versus Claude on Bedrock). | Strands tracing, one table. | results/cost.json. This is for Rohini and Ian. |

One command regenerates all five. scripts/verify_claims.py fails CI if README numbers drift from results.

## 6. Honesty envelope

- The Mitigation Trip request is drafted, not placed. BART requires the rider to tell a Station Agent or use the call box.
- Pathway and outage-option facts are scraped from BART pages on a stated date and could go stale. The scrape date is in the KB and on the status page.
- Only 14 stations have BART-documented options; for the other 22 the agent derives options from pathway data and says so in each message.
- Weekend outage volume is whatever it is. If the feed is quiet, the interruption number comes from a replay of archived outages, labeled as such.
- Real riders are not claimed unless at least three people register real trips before Sunday night. Report the count, whatever it is.
- No ridership statistics are cited unless fetched from a BART source during the build.

## 7. Day plan (Pacific)

| When | Deliverable | Acceptance test |
|---|---|---|
| Fri 9am to noon | BART key, feed poller writing to SQLite every 5 min, station list, scrape of accessibility pages into kb/stations/*.json with source URLs and scrape timestamp. | `make poll` records an outage snapshot; `make kb` produces 36 station files; both under test. |
| Fri noon to 6pm | Strands Agent with the three tools, structured output schema, steering handler, hook, verify step. Runs end to end on one synthetic outage against a registered trip. | `make demo-one` prints a plan with grounded stations and computed minutes. |
| Fri 6pm to 10pm | Policy agreement eval on the 14 documented stations. Fix until 100 percent or document why not. Blog post 1 drafted. | `make evals` writes policy_agreement.json. |
| Sat morning | AgentCore Runtime deploy (fallback Lambda plus EventBridge if quota is 0), public status page, SNS or email delivery to a test number. | Public URL loads; a forced outage produces a message on the test phone. |
| Sat afternoon | Interruption and relevance evals on the Fri to Sat archive, ablation run, cost table. README, JUDGING.md, architecture diagram. Blog posts 2 and 3 drafted. | `make evals` regenerates all results; verify_claims passes. |
| Sat night | Recruit riders. Register at least three real trips if possible. Freeze at 11:59pm Sunday, so Sunday is polish only. | Rider count recorded in results. |
| Sun (around the REI shift) | Clean-clone run, video script, publish three Builder Center posts, DEVPOST.md. Freeze. | Fresh clone passes JUDGING.md route in under 60 seconds. |
| Mon by 11am | Record and upload video, fill Devpost form, submit by 1pm. | Submitted. |

## 8. Submission surfaces

- README opens with the interruption number and one screenshot of a real message, then a table with one row per criterion and a link to its proof.
- JUDGING.md. `git clone`, `make replay`, open the status page, read one message. Under 60 seconds, no key needed, because replay uses the archived feed.
- Video (under 5 minutes). Number first. A real outage from the weekend. The rider's registered trip. The agent's message with the BART-ranked option. The steering handler catching a bad plan in the ablation. What is simulated. Strands and AgentCore named on screen.
- Builder Center posts, all with "Agents for Humans" in the title. 1. Turning BART's elevator policy into a Strands steering handler. 2. Measuring an agent by how rarely it interrupts, with Strands Evals. 3. Deploying a scheduled background agent on AgentCore, including the quota problem if it happens.
- Built With. Strands Agents, Amazon Bedrock, Amazon Bedrock AgentCore, Amazon SNS, Python, Kiro if used.

## 9. Risks and the day they are retired

- BART API key or rate limit trouble. Retired Fri noon by having a working poller; fallback is the GTFS-RT alerts feed.
- AgentCore quota 0. Retired Sat noon; fallback Lambda plus EventBridge keeps the live URL.
- Quiet weekend feed. Retired by the replay mode, which is required anyway for judges.
- Scraping BART pages is brittle. Retired Fri morning by committing the scraped JSON with source URLs so the build never depends on live scraping.
- Over-scope. The status page is one HTML file. No mobile app. No Muni or AC Transit routing beyond naming the operator BART's page names.
