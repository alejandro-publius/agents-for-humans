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
- **assistant -> tool** `get_station_facts` {"station_abbr": "ZZZZ"}
- **tool result** [CANCELLED] CANCELLED by ArgumentValidatorHook: station_abbr='ZZZZ' is not a known station
- **assistant -> tool** `Plan` {"affected": false, "option": "none", "steps": [], "message": "Station unknown; no plan."}
- **tool result** [success] Successfully validated Plan structured output
- **Plan**: `{"affected":false,"option":"none","steps":[],"added_minutes":null,"needs_human_decision":false,"message":"Station unknown; no plan."}`

### harness_hook / known_station_is_executed  PASS

- Prompt: `Outage: DELN: Platform - Richmond. Trip DELN to EMBR.`
- Model script: `fixtures/model/hook_good_station.json` (mock provider)
- Expected `first_tool_status`: `executed`  Observed: `executed`

Conversation:
- **user**: Outage: DELN: Platform - Richmond. Trip DELN to EMBR.
- **assistant -> tool** `get_station_facts` {"station_abbr": "DELN"}
- **tool result** [success] {"abbr": "DELN", "name": "El Cerrito del Norte", "elevators": [{"name": "PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)", "kind": "platform", "enter_option": "backtracking", "exit_option": "backtracking", "
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
- **assistant**: Backtracking is the first feasible option under BART's published outage order. Draft withheld by policy: response recommends 'mitigation_shuttle' but the first feasible option is 'backtracking'.
- **steering rewrote the response**: response recommends 'mitigation_shuttle' but the first feasible option is 'backtracking'

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
- Expected `plan_option`: `alternate_elevator`  Observed: `alternate_elevator`

Conversation:
- **user**: Outage: EMBR: Street - Platform. Trip EMBR to ASHB.
- **assistant -> tool** `Plan` {"affected": true, "option": "alternate_elevator", "steps": ["Use the street elevator at the north entrance"], "added_minutes": 3, "needs_human_decision": false, "message": "The south street elevator is out; the north one works and adds about three minutes."}
- **tool result** [success] Successfully validated Plan structured output
- **Plan**: `{"affected":true,"option":"alternate_elevator","steps":["Use the street elevator at the north entrance"],"added_minutes":3,"needs_human_decision":false,"message":"The south street elevator is out; the north one works and adds about three minutes."}`

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

## Suite `outage_parse`

Free-text outage fragment -> {station_abbr, level_from, level_to, platform_label, kb_elevator}. The model proposes (mock: scripted proposal per case); code validates against kb/ and resolves the elevator. Case 1 is BART's documented sample; the rest are authored in the same shape from KB elevator names. A regex baseline is reported alongside.

### outage_parse / deln_platform_richmond_documented_sample  PASS

- Fragment: `DELN: Platform - Richmond` (https://api.bart.gov/docs/bsa/elev.aspx documented sample)
- Model proposal (mock provider, scripted): `{"station_abbr": "DELN", "level_from": "platform", "level_to": null, "platform_label": "Richmond"}`
- Code validation: `{"station_abbr": "DELN", "level_from": "platform", "level_to": null, "platform_label": "Richmond", "kb_elevator": "PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)"}`
- Expected: `{"station_abbr": "DELN", "level_from": "platform", "level_to": null, "platform_label": "Richmond", "kb_elevator": "PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)"}`

### outage_parse / sanl_platform_sfo_direction  PASS

- Fragment: `SANL: Platform - SFO/Millbrae/Daly City` (authored)
- Model proposal (mock provider, scripted): `{"station_abbr": "SANL", "level_from": "platform", "level_to": null, "platform_label": "SFO/Millbrae/Daly City"}`
- Code validation: `{"station_abbr": "SANL", "level_from": "platform", "level_to": null, "platform_label": "SFO/Millbrae/Daly City", "kb_elevator": "PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS)"}`
- Expected: `{"station_abbr": "SANL", "level_from": "platform", "level_to": null, "platform_label": "SFO/Millbrae/Daly City", "kb_elevator": "PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS)"}`

### outage_parse / plza_platform_richmond  PASS

- Fragment: `PLZA: Platform - Richmond` (authored)
- Model proposal (mock provider, scripted): `{"station_abbr": "PLZA", "level_from": "platform", "level_to": null, "platform_label": "Richmond"}`
- Code validation: `{"station_abbr": "PLZA", "level_from": "platform", "level_to": null, "platform_label": "Richmond", "kb_elevator": "PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)"}`
- Expected: `{"station_abbr": "PLZA", "level_from": "platform", "level_to": null, "platform_label": "Richmond", "kb_elevator": "PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)"}`

### outage_parse / embr_street_concourse  PASS

- Fragment: `EMBR: Street - Concourse` (authored)
- Model proposal (mock provider, scripted): `{"station_abbr": "EMBR", "level_from": "street", "level_to": "concourse", "platform_label": null}`
- Code validation: `{"station_abbr": "EMBR", "level_from": "street", "level_to": "concourse", "platform_label": null, "kb_elevator": "STREET ELEVATOR"}`
- Expected: `{"station_abbr": "EMBR", "level_from": "street", "level_to": "concourse", "platform_label": null, "kb_elevator": "STREET ELEVATOR"}`

### outage_parse / 12th_street_ogawa_plaza  PASS

- Fragment: `12TH: Street - 14th St/Ogawa Plaza` (authored)
- Model proposal (mock provider, scripted): `{"station_abbr": "12TH", "level_from": "street", "level_to": null, "platform_label": "14th St/Ogawa Plaza"}`
- Code validation: `{"station_abbr": "12TH", "level_from": "street", "level_to": null, "platform_label": "14th St/Ogawa Plaza", "kb_elevator": "STREET ELEVATOR (14TH STREET/OGAWA PLAZA)"}`
- Expected: `{"station_abbr": "12TH", "level_from": "street", "level_to": null, "platform_label": "14th St/Ogawa Plaza", "kb_elevator": "STREET ELEVATOR (14TH STREET/OGAWA PLAZA)"}`

### outage_parse / ashb_street_concourse  PASS

- Fragment: `ASHB: Street - Concourse` (authored)
- Model proposal (mock provider, scripted): `{"station_abbr": "ASHB", "level_from": "street", "level_to": "concourse", "platform_label": null}`
- Code validation: `{"station_abbr": "ASHB", "level_from": "street", "level_to": "concourse", "platform_label": null, "kb_elevator": "STREET ELEVATOR"}`
- Expected: `{"station_abbr": "ASHB", "level_from": "street", "level_to": "concourse", "platform_label": null, "kb_elevator": "STREET ELEVATOR"}`

### outage_parse / mcar_platform_antioch_richmond  PASS

- Fragment: `MCAR: Platform - Antioch/Richmond` (authored)
- Model proposal (mock provider, scripted): `{"station_abbr": "MCAR", "level_from": "platform", "level_to": null, "platform_label": "Antioch/Richmond"}`
- Code validation: `{"station_abbr": "MCAR", "level_from": "platform", "level_to": null, "platform_label": "Antioch/Richmond", "kb_elevator": "PLATFORMS 1 AND 3 ELEVATOR (ANTIOCH, RICHMOND DIRECTIONS)"}`
- Expected: `{"station_abbr": "MCAR", "level_from": "platform", "level_to": null, "platform_label": "Antioch/Richmond", "kb_elevator": "PLATFORMS 1 AND 3 ELEVATOR (ANTIOCH, RICHMOND DIRECTIONS)"}`

### outage_parse / wdub_garage_north_is_ambiguous  PASS

- Fragment: `WDUB: Garage - North/Dublin` (authored; two garage elevators share the north side, so code must refuse to pick one)
- Model proposal (mock provider, scripted): `{"station_abbr": "WDUB", "level_from": "garage", "level_to": null, "platform_label": "North/Dublin"}`
- Code validation: `{"station_abbr": "WDUB", "level_from": "garage", "level_to": null, "platform_label": "North/Dublin", "kb_elevator": null}`
- Problems recorded by code: ['no unique KB elevator matches the fragment']
- Expected: `{"station_abbr": "WDUB", "level_from": "garage", "level_to": null, "platform_label": "North/Dublin", "kb_elevator": null}`

### outage_parse / unknown_station_is_nulled_by_code  PASS

- Fragment: `ZZZZ: Platform - Nowhere` (authored; the model echoes ZZZZ and code must null it)
- Model proposal (mock provider, scripted): `{"station_abbr": "ZZZZ", "level_from": "platform", "level_to": null, "platform_label": "Nowhere"}`
- Code validation: `{"station_abbr": null, "level_from": "platform", "level_to": null, "platform_label": "Nowhere", "kb_elevator": null}`
- Problems recorded by code: ["station 'ZZZZ' is not in the KB"]
- Expected: `{"station_abbr": null, "level_from": "platform", "level_to": null, "platform_label": "Nowhere", "kb_elevator": null}`

### outage_parse / cols_platform_falls_back_to_station_elevator  PASS

- Fragment: `COLS: Platform - Fruitvale` (authored; Coliseum's only street-to-platform elevator is headed STATION ELEVATOR)
- Model proposal (mock provider, scripted): `{"station_abbr": "COLS", "level_from": "platform", "level_to": null, "platform_label": "Fruitvale"}`
- Code validation: `{"station_abbr": "COLS", "level_from": "platform", "level_to": null, "platform_label": "Fruitvale", "kb_elevator": "STATION ELEVATOR"}`
- Expected: `{"station_abbr": "COLS", "level_from": "platform", "level_to": null, "platform_label": "Fruitvale", "kb_elevator": "STATION ELEVATOR"}`

## Suite `policy_agreement`

One case per (station, elevator, condition) from kb/stations. Label = the option label derived from BART's documented text (kb/labels.py). Output is the option the model put in its Plan before code verification. Mock mode proves plumbing (scripted model echoes the label); live mode reports the real number and is capped by --max-model-calls.

| station | elevator | condition | KB label | model option | policy top | agree |
| --- | --- | --- | --- | --- | --- | --- |
| 12TH | STREET ELEVATOR (14TH STREET/OGAWA PLAZA) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| 12TH | STREET ELEVATOR (14TH STREET/OGAWA PLAZA) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| 12TH | STREET ELEVATOR (11TH STREET/CONVENTION CENTER) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| 12TH | STREET ELEVATOR (11TH STREET/CONVENTION CENTER) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| 12TH | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| 12TH | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| 16TH | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| 16TH | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| 16TH | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| 16TH | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| 19TH | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| 19TH | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| 19TH | PLATFORM ELEVATOR 1 (NEAR 17th ST EXIT) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| 19TH | PLATFORM ELEVATOR 1 (NEAR 17th ST EXIT) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| 19TH | PLATFORM ELEVATOR 2 (NEAR 20th ST EXIT) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| 19TH | PLATFORM ELEVATOR 2 (NEAR 20th ST EXIT) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| 24TH | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| 24TH | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| 24TH | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| 24TH | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| ANTC | STREET ELEVATOR (CONCOURSE TO WALKWAY) | cant_enter | transit | transit | transit | yes |
| ANTC | STREET ELEVATOR (CONCOURSE TO WALKWAY) | cant_exit | transit | transit | transit | yes |
| ANTC | PLATFORM ELEVATOR (WALKWAY TO PLATFORM) | cant_enter | transit | transit | transit | yes |
| ANTC | PLATFORM ELEVATOR (WALKWAY TO PLATFORM) | cant_exit | transit | transit | transit | yes |
| ASHB | PLATFORM ELEVATOR 1 | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| ASHB | PLATFORM ELEVATOR 1 | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| ASHB | PLATFORM ELEVATOR 2 | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| ASHB | PLATFORM ELEVATOR 2 | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| ASHB | STREET ELEVATOR | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| ASHB | STREET ELEVATOR | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| BALB | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| BALB | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| BAYF | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| BAYF | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| BERY | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| BERY | STATION ELEVATOR | cant_exit | backtracking | backtracking | backtracking | yes |
| CAST | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| CAST | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| CIVC | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| CIVC | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| CIVC | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| CIVC | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| COLM | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| COLM | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| COLS | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| COLS | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| COLS | ELEVATOR TO OAKLAND AIRPORT CONNECTOR | can_t_access_connector_platform | transit | transit | transit | yes |
| COLS | ELEVATOR TO OAKLAND AIRPORT CONNECTOR | can_t_exit_connect_connector_platform | backtracking | backtracking | backtracking | yes |
| COLS | WHEELCHAIR LIFT FROM STATION TO PARKING LOT | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| COLS | WHEELCHAIR LIFT FROM STATION TO PARKING LOT | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| COLS | PEDESTRIAN BRIDGE ELEVATOR TO ARENA | can_t_access_arena | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| COLS | PEDESTRIAN BRIDGE ELEVATOR TO ARENA | can_t_leave_arena | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| CONC | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| CONC | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| DALY | PLATFORMS 1 AND 2 ELEVATOR (EAST BAY DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| DALY | PLATFORMS 1 AND 2 ELEVATOR (EAST BAY DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| DALY | PLATFORM 3 ELEVATOR (SFO/MILLBRAE DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| DALY | PLATFORM 3 ELEVATOR (SFO/MILLBRAE DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| DALY | ELEVATORS TO PEDESTRIAN TUNNEL | cant_enter_from_tunnel | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| DALY | ELEVATORS TO PEDESTRIAN TUNNEL | cant_exit_from_tunnel | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| DBRK | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| DBRK | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| DBRK | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| DBRK | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| DELN | PLATFORM 1 ELEVATOR (RICHMOND DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| DELN | PLATFORM 1 ELEVATOR (RICHMOND DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| DELN | PLATFORM 2 ELEVATOR (BERRYESSA, SFO/MILLBRAE/DALY CITY DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| DELN | PLATFORM 2 ELEVATOR (BERRYESSA, SFO/MILLBRAE/DALY CITY DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| DUBL | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| DUBL | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| EMBR | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| EMBR | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| EMBR | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| EMBR | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| FRMT | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| FRMT | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| FTVL | PLATFORM 2 ELEVATOR (RICHMOND, MILLBRAE/SFO/DALY CITY DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| FTVL | PLATFORM 2 ELEVATOR (RICHMOND, MILLBRAE/SFO/DALY CITY DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| FTVL | PLATFORM 1 ELEVATOR (DUBLIN, BERRYESSA DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| FTVL | PLATFORM 1 ELEVATOR (DUBLIN, BERRYESSA DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| GLEN | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| GLEN | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| HAYW | PLATFORM 2 ELEVATOR (RICHMOND, DALY CITY DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| HAYW | PLATFORM 2 ELEVATOR (RICHMOND, DALY CITY DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| HAYW | PLATFORM 1 ELEVATOR (BERRYESSA DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| HAYW | PLATFORM 1 ELEVATOR (BERRYESSA DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| LAFY | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| LAFY | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| LAKE | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| LAKE | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| LAKE | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| LAKE | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| MCAR | PLATFORMS 2 AND 4 ELEVATOR (SFO/MILLBRAE/DALY CITY, BERRYESSA DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| MCAR | PLATFORMS 2 AND 4 ELEVATOR (SFO/MILLBRAE/DALY CITY, BERRYESSA DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| MCAR | PLATFORMS 1 AND 3 ELEVATOR (ANTIOCH, RICHMOND DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| MCAR | PLATFORMS 1 AND 3 ELEVATOR (ANTIOCH, RICHMOND DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| MLBR | STREET ELEVATOR FROM THE EAST PLAZA | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| MLBR | STREET ELEVATOR FROM THE EAST PLAZA | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| MLBR | CALTRAIN ELEVATOR - WEST PLAZA TO CONCOURSE | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| MLBR | CALTRAIN ELEVATOR - WEST PLAZA TO CONCOURSE | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| MLBR | PLATFORM 3 ELEVATOR (ALL DESTINATIONS) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| MLBR | PLATFORM 3 ELEVATOR (ALL DESTINATIONS) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| MLBR | CALTRAIN ELEVATOR - CONCOURSE TO NORTHBOUND PLATFORM | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| MLBR | CALTRAIN ELEVATOR - CONCOURSE TO NORTHBOUND PLATFORM | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| MLPT | PLATFORM 1 ELEVATOR (BERRYESSA DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| MLPT | PLATFORM 1 ELEVATOR (BERRYESSA DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| MLPT | PLATFORM 2 ELEVATOR (MILLBRAE/SFO/DALY CITY/RICHMOND DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| MLPT | PLATFORM 2 ELEVATOR (MILLBRAE/SFO/DALY CITY/RICHMOND DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| MONT | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| MONT | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| MONT | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| MONT | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| NBRK | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| NBRK | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| NCON | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| NCON | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| OAKL | ELEVATOR TO OAKLAND AIRPORT CONNECTOR | can_t_access_connector | transit | transit | transit | yes |
| OAKL | ELEVATOR TO OAKLAND AIRPORT CONNECTOR | can_t_exit_to_airport | backtracking | backtracking | backtracking | yes |
| ORIN | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| ORIN | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| PCTR | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| PCTR | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| PHIL | PLATFORM 1 ELEVATOR (ANTIOCH DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| PHIL | PLATFORM 1 ELEVATOR (ANTIOCH DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| PHIL | PLATFORM 2 ELEVATOR (SFO/MILLBRAE/DALY CITY DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| PHIL | PLATFORM 2 ELEVATOR (SFO/MILLBRAE/DALY CITY DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| PITT | STREET ELEVATOR | cant_enter | transit | transit | transit | yes |
| PITT | STREET ELEVATOR | cant_exit | transit | transit | transit | yes |
| PITT | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| PITT | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| PLZA | PLATFORM 1 ELEVATOR (RICHMOND DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| PLZA | PLATFORM 1 ELEVATOR (RICHMOND DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| PLZA | PLATFORM 2 ELEVATOR (BERRYESSA, SFO/MILLBRAE/DALY CITY DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| PLZA | PLATFORM 2 ELEVATOR (BERRYESSA, SFO/MILLBRAE/DALY CITY DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| POWL | STREET ELEVATOR | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| POWL | STREET ELEVATOR | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| POWL | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| POWL | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| RICH | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| RICH | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| RICH | STREET ELEVATOR (EAST SIDE OF STATION) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| RICH | STREET ELEVATOR (EAST SIDE OF STATION) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| RICH | STREET ELEVATOR (WEST SIDE OF STATION) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| RICH | STREET ELEVATOR (WEST SIDE OF STATION) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| ROCK | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| ROCK | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| SANL | PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| SANL | PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| SANL | PLATFORM 1 ELEVATOR (DUBLIN, BERRYESSA DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| SANL | PLATFORM 1 ELEVATOR (DUBLIN, BERRYESSA DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| SBRN | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| SBRN | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| SFIA | PLATFORMS 1 AND 2 ELEVATOR (ALL DESTINATIONS) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| SFIA | PLATFORMS 1 AND 2 ELEVATOR (ALL DESTINATIONS) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| SFIA | PLATFORMS 3 AND 4 ELEVATOR (ALL DESTINATIONS) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| SFIA | PLATFORMS 3 AND 4 ELEVATOR (ALL DESTINATIONS) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| SHAY | STATION ELEVATOR - STREET TO PLATFORM 1 AND BRIDGE (BERRYESSA DIRECTION) | cant_enter | transit | transit | transit | yes |
| SHAY | STATION ELEVATOR - STREET TO PLATFORM 1 AND BRIDGE (BERRYESSA DIRECTION) | cant_exit | transit | transit | transit | yes |
| SHAY | PLATFORM ELEVATOR - BRIDGE TO PLATFORM 2 (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| SHAY | PLATFORM ELEVATOR - BRIDGE TO PLATFORM 2 (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| SSAN | STATION ELEVATOR | cant_enter | transit | transit | transit | yes |
| SSAN | STATION ELEVATOR | cant_exit | transit | transit | transit | yes |
| UCTY | PLATFORM 1 ELEVATOR (BERRYESSA DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| UCTY | PLATFORM 1 ELEVATOR (BERRYESSA DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| UCTY | PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| UCTY | PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |
| WARM | STREET ELEVATOR 1 | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WARM | STREET ELEVATOR 1 | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WARM | STREET ELEVATOR 2 | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WARM | STREET ELEVATOR 2 | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WARM | PLATFORM ELEVATOR 1 | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WARM | PLATFORM ELEVATOR 1 | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WARM | PLATFORM ELEVATOR 2 | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WARM | PLATFORM ELEVATOR 2 | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WARM | PEDESTRIAN BRIDGE ELEVATOR | cant_enter | transit | transit | transit | yes |
| WARM | PEDESTRIAN BRIDGE ELEVATOR | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WCRK | PLATFORM 1 ELEVATOR (ANTIOCH DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| WCRK | PLATFORM 1 ELEVATOR (ANTIOCH DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| WCRK | PLATFORM 2 ELEVATOR (SFO/MILLBRAE/DALY CITY DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| WCRK | PLATFORM 2 ELEVATOR (SFO/MILLBRAE/DALY CITY DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| WDUB | GARAGE ELEVATOR 2 (NORTH/DUBLIN SIDE) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WDUB | GARAGE ELEVATOR 2 (NORTH/DUBLIN SIDE) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WDUB | GARAGE ELEVATOR 1 (NORTH/DUBLIN SIDE) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WDUB | GARAGE ELEVATOR 1 (NORTH/DUBLIN SIDE) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WDUB | GARAGE ELEVATOR 1 (SOUTH/PLEASANTON SIDE) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WDUB | GARAGE ELEVATOR 1 (SOUTH/PLEASANTON SIDE) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WDUB | GARAGE ELEVATOR 2 (SOUTH/PLEASANTON SIDE) | cant_enter | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WDUB | GARAGE ELEVATOR 2 (SOUTH/PLEASANTON SIDE) | cant_exit | alternate_elevator | alternate_elevator | alternate_elevator | yes |
| WDUB | PLATFORM ELEVATOR | cant_enter | transit | transit | transit | yes |
| WDUB | PLATFORM ELEVATOR | cant_exit | transit | transit | transit | yes |
| WOAK | PLATFORM 1 ELEVATOR (SFO/MILLBRAE/DALY CITY DIRECTION) | cant_enter | backtracking | backtracking | backtracking | yes |
| WOAK | PLATFORM 1 ELEVATOR (SFO/MILLBRAE/DALY CITY DIRECTION) | cant_exit | backtracking | backtracking | backtracking | yes |
| WOAK | PLATFORM 2 ELEVATOR (DUBLIN/ANTIOCH/RICHMOND/BERRYESSA DIRECTIONS) | cant_enter | backtracking | backtracking | backtracking | yes |
| WOAK | PLATFORM 2 ELEVATOR (DUBLIN/ANTIOCH/RICHMOND/BERRYESSA DIRECTIONS) | cant_exit | backtracking | backtracking | backtracking | yes |

---
211/211 cases matched their label.
