# Onboarding another agency

BART today; the same harness plus a new station KB applies to any agency
with an elevator feed and a published policy. Nothing in the gates, the
red team, the Cedar generator, the evaluation dataset, the messages or the
convergence study knows about BART. `tests/test_portability.py` proves it
by running every stage on a synthetic agency with other station codes, a
different published option order and other minutes, with zero code
changes. This page is what an agency (or a volunteer) supplies.

## 1. The knowledge base (one JSON file)

```json
{
  "source": "where the codes and options came from (the agency's station pages)",
  "frozen_tag": "kb-<agency>-v1",
  "stations": ["ATN0", "BTN1"],
  "elevators": ["ATN0-E1", "ATN0-E2"],
  "option_labels": ["backtracking", "alternate_elevator", "transit"],
  "station_names": {"ATN0": "A Town", "BTN1": "B Town"}
}
```

`option_labels` is the agency's own published order of sanctioned options,
first is best. `station_names` is optional and worth filling in: a screen
reader spells a code letter by letter, so every approved sentence and every
decision card says the name when the KB has one and the code otherwise. Station codes are four characters (letters and digits);
elevator ids are `<station>-E<n>`. Labels outside the five known ones work
everywhere except the plain-language wording in messages, which falls back
to the label itself; add the wording to `LABEL_WORDS_PLAIN` in
`le_dispatch/messages.py` when the agency uses its own terms.

## 2. The cases (one JSON file)

One row per option the agency publishes for an elevator: station,
elevator, label, the agency's own option text, the added minutes the
agency's policy implies (or null), and the source URL. Two human labelers
per row, frozen at a tag, as with BART.

## 3. The policy callable

`policy(trip) -> PolicyDecision`: affectedness (cannot enter, cannot exit,
transfer) from the trip and the outage set, the agency's options for the
elevator ranked in the agency's published order, minutes from the rows.
`FixturePolicy` in `le_dispatch/interfaces.py` implements the contract
from the cases file and is enough for a first deployment; a richer engine
(route knowledge, time of day, last-train tables) replaces it behind the
same callable.

## 4. The feed

A poller that reads the agency's elevator status feed every five minutes
and diffs snapshots into the archive schema (`le_dispatch/dataset_export.py`
documents the columns). The parser that turns the agency's outage text into
station and elevator ids is the one agency-specific piece of code.

## 5. Then, unchanged

`make verify`, `make red-team-exhaustive`, `make convergence`,
`make agentcore-policy-gen --kb <file>`, `make agentcore-eval --kb <file>
--cases <file>`, `make evidence`, and the runtime entrypoint. The
guarantees carry over because they are properties of the harness, not of
BART: the model never asserts a code outside the KB, never computes
minutes, never overrides the published order, never sends a sentence it
wrote alone, and the rider always gets a plan.
