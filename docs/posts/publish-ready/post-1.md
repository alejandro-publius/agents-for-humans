Title: Agents for Humans: an agent that warns, reroutes and informs a BART rider before the elevator does
Tags: strands-agents, amazon-bedrock, agentcore, python, accessibility, hackathon
Community: Agents for Humans hackathon (Everyday track)
Words: 728
Fill before publishing: the two links on the last line (the public repo URL and the video URL).

----- paste from here -----

A BART rider who depends on elevators is stuck checking outage alerts and
re-planning the same trip, over and over. This post is about Last
Elevator, an Everyday-track agent built with the Strands Agents SDK for
the Agents for Humans hackathon, and about why the problem is bigger than
one transit system.

## The problem is a civil-rights problem

On July 29, 2026, disability advocates settled a class action filed in
2017 against New York's MTA over subway elevator outages. The settlement
requires alternate accessible travel information at every accessibility
elevator, platform announcements every fifteen minutes about long-term
outages, on-board announcements for outages lasting more than fourteen
days, a phone line for accessible rerouting help, and real-time outage
information in the MTA's app. A plaintiff summarized the status quo:
riders check the app before they leave the house, and the information is
not updated.

The numbers are the same everywhere. MTA reports 97 to 98 percent elevator
availability a month; BART's published goal is 98 percent. At that goal,
two of every hundred elevators are out at any moment, and some BART
stations need two different elevators to get from street to platform, so
one outage can cut a station off entirely. The WHO counts 1.3 billion
people, one in six worldwide, living with a significant disability.
Chicago's CTA already posts system-wide elevator outages at each station
because riders need to know before they board whether they can exit at
their destination.

Last Elevator does for one rider what the settlement now requires an
agency to do for everyone: warn, reroute, and inform in real time, using
the agency's own published policy. It automates the rider's side of the
information problem. It does not satisfy any settlement or ADA
requirement, and this post does not claim it does.

## What runs in the background

A poller watches BART's elevator outage feed every five minutes and diffs
snapshots into sqlite. A parser turns "DELN: Platform - Richmond" into a
structured outage. A trip matcher and a policy engine, pure code with no
model, decide whether a saved trip is affected and rank BART's own
sanctioned options in BART's published order: alternate_elevator,
backtracking, transit, mitigation_trip, mitigation_shuttle. The knowledge
base holds 194 labeled options across 97 elevators at 50 stations, read
from BART's station pages and frozen. A Strands agent drafts the plan and
the rider's message. The rider hears nothing unless the trip is affected,
and one outage is one message: a plan already sent is not sent again
while the outage lasts, and no model runs for the repeat.

What the rider hears is written for a screen reader: the station's name
rather than a code spelled letter by letter, BART's option in words
rather than a label, the minutes from the policy engine, and never a
sentence the model wrote alone (code composes a few sentences from the
decision and BART's own wording; the model only picks one). A rider can
also say, in their own words, what they cannot do today ("no ramps, I am
pushing a stroller"): the model may read the note only into a fixed
vocabulary with the rider's words as the reason, and code applies it as
feasibility, so a note can take an option away and never add, reorder or
number one.

## When the human is asked

After dark, or at the last train, the run pauses with a Strands
`Interrupt`. The rider gets a decision card: BART's option, the added
minutes from the policy engine, the flags, the source URL, and the
rejected options with one-line reasons. The answer is stored in session
state, so the same case never interrupts twice, and if the elevator comes
back before the rider answers, the question is withdrawn rather than left
hanging; when the elevator is back, the answer goes with the outage, so
the next outage asks afresh. In a synthetic week for
three synthetic riders the quiet report opened with "7 days, 2
interruptions, 2 decisions" (a synthetic replay; the archive replay is
pending).

## What is next

Post 2 covers the two-stage gate that keeps the model from inventing a
station or a number. Post 3 covers the evidence packet: the trace and the
decision card a judge, or a rider, can read.

Sources: DRA press release (https://dralegal.org/press/ny-subway-elevators-settlement/),
amNY (https://www.amny.com/nyc-transit/mta-and-disability-groups-elevator-accessibility/),
WHO (https://www.who.int/news-room/fact-sheets/detail/disability-and-health),
BART elevator pages (https://www.bart.gov/guide/accessibility/elevators).

Repo: TODO. Video: TODO.
