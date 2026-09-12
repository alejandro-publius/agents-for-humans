# Reusable pattern: compliance steering + unknown-entity hook

`compliance_steering.py` is a single standalone file (Strands SDK only, no BART data, no network,
no credentials) that shows the two guardrails Last Elevator is built on:

1. **Compliance steering.** A `SteeringHandler` whose `steer_before_tool` returns `Guide` when the
   model proposes anything but the first feasible option of an external ranked policy. The tool call
   is cancelled, the reason is fed back, the model retries.
2. **Unknown-entity hook.** A `HookProvider` on `BeforeToolCallEvent` that sets `event.cancel_tool`
   when a tool argument names an entity outside your reference data.

```bash
python examples/compliance_steering.py
# hook cancelled unknown assets : ['PUMP-9']
# steering guided wrong options : ['escalate']
# final answer                  : Proposed: repair PUMP-1 in place (replace the seal).
# demo OK
```

The demo drives a scripted model so both mechanisms fire deterministically; swap in
`BedrockModel()` for a live run. The same file is prepared as a branch on a fork of the Strands
samples repository (see `docs/reports/day-1.md`, E6) for a pull request the maintainers can review.
