# Narrative blocks (section 4b), sourced

Use these verbatim or lightly adapted in the README, the Devpost
description, the video opening and post 1. Every figure here has a source
link; anything not listed here is not published.

## The person (organizers' template)

A BART rider who depends on elevators is stuck checking outage alerts and
re-planning the same trip, over and over.

## The opening context: a civil-rights issue, not a convenience feature

On July 29, 2026, disability advocates settled a class action filed in
2017 against New York's MTA over subway elevator outages. The settlement
requires alternate accessible travel information posted at every
accessibility elevator, platform announcements every fifteen minutes about
long-term outages, on-board announcements for outages lasting more than
fourteen days, a phone line for accessible rerouting assistance, and
real-time outage information on the MTA's website and app. A plaintiff's
summary of the status quo: riders check the app before they leave the
house, and the information is not updated.

Last Elevator does for one rider what the settlement now requires an
agency to do for everyone: warn, reroute, and inform in real time, using
the agency's own published policy.

## The availability numbers are the same everywhere

MTA's CEO puts subway elevator availability at 97 to 98 percent a month;
BART's published goal is 98 percent. At that goal, two of every hundred
elevators are out at any moment, and BART notes that some stations need
two different elevators to get from street to platform, so one outage can
cut a station off entirely. BART itself settled a 2017 class action over
elevator and escalator upkeep brought by Senior and Disability Action and
the Independent Living Resource Center of San Francisco.

## Scale

The WHO counts 1.3 billion people, one in six worldwide, living with a
significant disability. Every US rail agency with elevators has this
exact problem; Chicago's CTA already posts system-wide elevator outages at
each station because riders need to know before they board whether they
can exit at their destination. BART today; the same harness plus a new
station KB applies to any agency with an elevator feed and a published
policy.

## Why AWS cares

Amazon's Global Accessibility Awareness Month is its largest disability
inclusion initiative; AWS's head of accessibility experience calls
accessibility a cornerstone of the AWS customer experience and points to
Werner Vogels' re:Invent 2023 keynote: accessibility at AWS is not
negotiable.

## Guardrail on claims (binding)

Never state or imply that Last Elevator satisfies any settlement or ADA
requirement. It automates the rider's side of the information problem.
Cite the settlement as context, not as a claim about the product. Do not
publish a CDC or census disability statistic without checking it on
cdc.gov first; this package publishes the WHO figure only.

## Judge vocabulary, once each, only where accurate

- neurosymbolic guardrail: the hook plus the two steering gates. The model
  proposes; code decides.
- evidence packet: the decision card with its source URL and the trace of
  which gate fired.
- architecture over model choice: the two-model policy-agreement table,
  once the live rows exist.

## The Strands benchmark sentence, once, in the description

Strands' own steering benchmark reports prompt-only agents at 82.5
percent, hard-coded workflows at 80.8 percent, and agents with steering
handlers recovering from every mistake; our enforced versus no-steering
eval reproduces that benchmark's shape on a real transit policy.

## Sources

- Disability Rights Advocates press release, July 29, 2026:
  https://dralegal.org/press/ny-subway-elevators-settlement/
- amNY coverage of the settlement:
  https://www.amny.com/nyc-transit/mta-and-disability-groups-elevator-accessibility/
- WHO fact sheet, disability and health (1.3 billion, one in six):
  https://www.who.int/news-room/fact-sheets/detail/disability-and-health
- BART elevator locations, outage options and accessible pathways (the
  station pages the KB was read from): https://www.bart.gov/guide/accessibility/elevators
- BART live elevator status: https://www.bart.gov/stations/elevators
- BART 2017 settlement coverage, San Francisco Chronicle:
  https://www.sfchronicle.com/politics/article/bart-disabled-settlement-19410327.php
- CTA elevator status page: https://www.transitchicago.com/travel-information/elevator-status/
- BART's 98 percent availability goal: cite BART's published performance
  goal from the main repo's day-1 report source list (verify the URL on
  bart.gov before publishing).
