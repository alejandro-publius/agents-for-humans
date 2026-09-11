# Replay (offline, mock provider)

Every eval case run through the real Strands agent loop with a scripted model. Tool calls, hook
cancellations, steering rewrites, and the final structured Plan are shown as they happened.
Nothing here touched the network. Regenerate with `make replay`.

## Suite `harness_hook`

Does the BeforeToolCall hook cancel tool calls whose arguments name an unknown station? Output is the status of the first tool call: 'cancelled' or 'executed'.

### harness_hook / unknown_station_is_cancelled  PASS

- Prompt: `Outage: ZZZZ: Platform - Nowhere. Trip DELN to EMBR.`
- Model script: `fixtures/model/hook_bad_station.json` (mock provider)
- Expected `first_tool_status`: `cancelled`  Observed: `cancelled`

Conversation:
- **user**: Outage: ZZZZ: Platform - Nowhere. Trip DELN to EMBR.
- **assistant -> tool** `get_station_facts` {"station": "ZZZZ"}
- **tool result** [CANCELLED] CANCELLED by ArgumentValidatorHook: station='ZZZZ' is not a known station
- **assistant -> tool** `Plan` {"affected": false, "option": "none", "steps": [], "message": "Station unknown; no plan."}
- **tool result** [success] Successfully validated Plan structured output
- **Plan**: `{"affected":false,"option":"none","steps":[],"added_minutes":null,"needs_human_decision":false,"message":"Station unknown; no plan."}`

### harness_hook / known_station_is_executed  PASS

- Prompt: `Outage: DELN: Platform - Richmond. Trip DELN to EMBR.`
- Model script: `fixtures/model/hook_good_station.json` (mock provider)
- Expected `first_tool_status`: `executed`  Observed: `executed`

Conversation:
- **user**: Outage: DELN: Platform - Richmond. Trip DELN to EMBR.
- **assistant -> tool** `get_station_facts` {"station": "DELN"}
- **tool result** [success] {"station": "DELN", "elevators": ["PLACEHOLDER"], "pathways": ["PLACEHOLDER"], "documented_outage_options": [], "source": "PLACEHOLDER until kb/ is built (B1)"}
- **assistant -> tool** `Plan` {"affected": true, "option": "backtracking", "steps": ["Ride one stop to Richmond", "Return on the next train"], "added_minutes": 12, "message": "Del Norte platform elevator is out. Ride to Richmond and come back; the other platform elevator works."}
- **tool result** [success] Successfully validated Plan structured output
- **Plan**: `{"affected":true,"option":"backtracking","steps":["Ride one stop to Richmond","Return on the next train"],"added_minutes":12,"needs_human_decision":false,"message":"Del Norte platform elevator is out. Ride to Richmond and come back; the other platform elevator works."}`

## Suite `harness_steering`

Does the steering handler make the final response recommend code's top feasible option? Output is the first option named in the final text.

### harness_steering / shuttle_draft_is_rewritten_to_backtracking  PASS

- Prompt: `Outage: DELN: Platform - Richmond. Trip DELN to EMBR.`
- Model script: `fixtures/model/steering_bad_order.json` (mock provider)
- Expected `first_option_in_text`: `backtracking`  Observed: `backtracking`

Conversation:
- **user**: Outage: DELN: Platform - Richmond. Trip DELN to EMBR.
- **assistant**: Backtracking is the first feasible option under BART's published outage order. Draft withheld by policy: response recommends 'mitigation shuttle' but the first feasible option is 'backtracking'.
- **steering rewrote the response**: response recommends 'mitigation shuttle' but the first feasible option is 'backtracking'

### harness_steering / compliant_draft_is_left_alone  PASS

- Prompt: `Outage: DELN: Platform - Richmond. Trip DELN to EMBR.`
- Model script: `fixtures/model/steering_good_order.json` (mock provider)
- Expected `first_option_in_text`: `backtracking`  Observed: `backtracking`

Conversation:
- **user**: Outage: DELN: Platform - Richmond. Trip DELN to EMBR.
- **assistant**: Use backtracking: ride one stop past Del Norte to Richmond, then return; the far platform elevator is working.

## Suite `harness_structured`

Does every run end in a schema-valid Plan? Output is plan.option from the structured output.

### harness_structured / immediate_plan  PASS

- Prompt: `Outage: EMBR: Street - Platform. Trip EMBR to ASHB.`
- Model script: `fixtures/model/structured_plan.json` (mock provider)
- Expected `plan_option`: `alternate elevator`  Observed: `alternate elevator`

Conversation:
- **user**: Outage: EMBR: Street - Platform. Trip EMBR to ASHB.
- **assistant -> tool** `Plan` {"affected": true, "option": "alternate elevator", "steps": ["Use the street elevator at the north entrance"], "added_minutes": 3, "needs_human_decision": false, "message": "The south street elevator is out; the north one works and adds about three minutes."}
- **tool result** [success] Successfully validated Plan structured output
- **Plan**: `{"affected":true,"option":"alternate elevator","steps":["Use the street elevator at the north entrance"],"added_minutes":3,"needs_human_decision":false,"message":"The south street elevator is out; the north one works and adds about three minutes."}`

### harness_structured / forced_plan_after_prose  PASS

- Prompt: `Outage: DELN: Platform - Richmond. Trip DELN to EMBR.`
- Model script: `fixtures/model/structured_forced.json` (mock provider)
- Expected `plan_option`: `backtracking`  Observed: `backtracking`

Conversation:
- **user**: Outage: DELN: Platform - Richmond. Trip DELN to EMBR.
- **assistant**: Here is my plan in prose: backtrack one stop and return.
- **user**: You must format the previous response as structured output.
- **assistant -> tool** `Plan` {"affected": true, "option": "backtracking", "steps": ["Ride one stop past", "Return"], "added_minutes": 12, "message": "Backtrack one stop and return."}
- **tool result** [success] Successfully validated Plan structured output
- **Plan**: `{"affected":true,"option":"backtracking","steps":["Ride one stop past","Return"],"added_minutes":12,"needs_human_decision":false,"message":"Backtrack one stop and return."}`

### harness_structured / invalid_plan_then_valid  PASS

- Prompt: `Outage: ASHB: Street - Platform. Trip ASHB to MONT.`
- Model script: `fixtures/model/structured_invalid_then_valid.json` (mock provider)
- Expected `plan_option`: `transit`  Observed: `transit`

Conversation:
- **user**: Outage: ASHB: Street - Platform. Trip ASHB to MONT.
- **assistant -> tool** `Plan` {"affected": true, "option": "transit", "steps": ["Take AC Transit 72"]}
- **tool result** [error] Validation failed for Plan. Please fix the following errors:
- Field 'message': Field required
- **assistant -> tool** `Plan` {"affected": true, "option": "transit", "steps": ["Take AC Transit 72"], "added_minutes": 25, "message": "Both platform elevators are out; take the 72 bus one stop."}
- **tool result** [success] Successfully validated Plan structured output
- **Plan**: `{"affected":true,"option":"transit","steps":["Take AC Transit 72"],"added_minutes":25,"needs_human_decision":false,"message":"Both platform elevators are out; take the 72 bus one stop."}`

---
7/7 cases matched their label.
