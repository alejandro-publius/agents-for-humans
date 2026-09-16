# The live path, offline: the agent through Strands' real Bedrock adapter

Everything between the agent and the network is the SDK's own code (`strands.models.BedrockModel`
formats the Converse request, parses the stream and raises its exceptions; the event loop retries what
it retries). Only the boto3 client is a stand-in that records every request, enforces the Converse
rules a retry can break (roles alternate; every toolUse answered; tool blocks need a toolConfig) with
Bedrock's ValidationException, and replays scripted chunks. The real client was pointed at a closed
local port before it was replaced; nothing was sent. Model id on the request: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`.

The first request of the compliant run is in `bedrock-request.json` next to this file: the system
prompt, the two tool specs (`draft_plan` and the structured-output tool `Plan`), the rider's prompt.

## Compliant model: two calls, the plan is the model's

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | tool_use draft_plan |
| 2 | u a u | yes | tool_use Plan |

Outcome: composed by model (tool_use); 2 model call(s), 2 request(s), 0 rejected by the Converse rules; hook cancels 0, Guides before the tool 0, after the model 0.

## Every gate, then two Guides in a row: every retry accepted at the first attempt

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | tool_use draft_plan |
| 2 | u a u | yes | tool_use draft_plan |
| 3 | u a u a u | yes | tool_use draft_plan |
| 4 | u a u a u a u | yes | tool_use Plan |
| 5 | u a u a u a u a u | yes | tool_use Plan |
| 6 | u a u a u a u a u | yes | tool_use Plan |

Outcome: composed by model (tool_use); 6 model call(s), 6 request(s), 0 rejected by the Converse rules; hook cancels 1, Guides before the tool 1, after the model 2.

## The same run with only the folding pass: the SDK's lazy separator costs one request

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | tool_use draft_plan |
| 2 | u a u | yes | tool_use draft_plan |
| 3 | u a u a u | yes | tool_use draft_plan |
| 4 | u a u a u a u | yes | tool_use Plan |
| 5 | u a u a u a u u | no | ValidationException: Conversation blocks and tool result blocks cannot be provided in the same turn. |
| 6 | u a u a u a u a u | yes | tool_use Plan |
| 7 | u a u a u a u a u | yes | tool_use Plan |

Outcome: composed by model (tool_use); 6 model call(s), 7 request(s), 1 rejected by the Converse rules; hook cancels 1, Guides before the tool 1, after the model 2.

## The same run with no pass: the second Guide is unsendable, code composes the plan

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | tool_use draft_plan |
| 2 | u a u | yes | tool_use draft_plan |
| 3 | u a u a u | yes | tool_use draft_plan |
| 4 | u a u a u a u | yes | tool_use Plan |
| 5 | u a u a u a u u | no | ValidationException: Conversation blocks and tool result blocks cannot be provided in the same turn. |
| 6 | u a u a u a u a u | yes | tool_use Plan |
| 7 | u a u a u a u a u u | no | ValidationException: (stand-in) roles must alternate between user and assistant |

Outcome: composed by code (exception); 6 model call(s), 7 request(s), 2 rejected by the Converse rules; hook cancels 1, Guides before the tool 1, after the model 2.
Reason: EventLoopException('An error occurred (ValidationException) when calling the ConverseStream operation: (stand-in) roles must alternate between user and assistant')

## A permission error on the model: one call, the rider still gets the plan

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | AccessDeniedException: An error occurred (AccessDeniedException) when calling the ConverseStream operation: You don't have access to the model  |

Outcome: composed by code (exception); 1 model call(s), 1 request(s), 0 rejected by the Converse rules; hook cancels 0, Guides before the tool 0, after the model 0.
Reason: ClientError("An error occurred (AccessDeniedException) when calling the ConverseStream operation: You don't have access to the model with the specified model ID.")

## A throttle: the SDK retries, then the plan

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | ThrottlingException: An error occurred (ThrottlingException) when calling the ConverseStream operation: Too many requests, please wait before |
| 2 | u | yes | tool_use draft_plan |
| 3 | u a u | yes | tool_use Plan |

Outcome: composed by model (tool_use); 3 model call(s), 3 request(s), 0 rejected by the Converse rules; hook cancels 0, Guides before the tool 0, after the model 0.

## A response cut off by the output token limit: one call, the rider still gets the plan

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | tool_use draft_plan |

Outcome: composed by code (exception); 1 model call(s), 1 request(s), 0 rejected by the Converse rules; hook cancels 0, Guides before the tool 0, after the model 0.
Reason: MaxTokensReachedException('Model stopped generating due to maximum token limit. The partial message has been added to the conversation history. You can continue by calling the agent again. For more information see: https://strandsagents.com/docs/user-guide/concepts/agents/agent-loop/#maxtokensreachedexception')

## A stream silent past the read timeout: one call, not retried, the rider still gets the plan

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | ReadTimeoutError: Read timeout on endpoint URL: "https://bedrock-runtime.us-west-2.amazonaws.com/" |

Outcome: composed by code (exception); 1 model call(s), 1 request(s), 0 rejected by the Converse rules; hook cancels 0, Guides before the tool 0, after the model 0.
Reason: ReadTimeoutError('Read timeout on endpoint URL: "https://bedrock-runtime.us-west-2.amazonaws.com/"')

## A prose answer instead of the Plan: the SDK's forced structured-output request (toolChoice any, a user instruction) is accepted, the plan is the model's

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | tool_use draft_plan |
| 2 | u a u | yes | text |
| 3 | u a u a u (toolChoice any) | yes | tool_use Plan |

Outcome: composed by model (tool_use); 3 model call(s), 3 request(s), 0 rejected by the Converse rules; hook cancels 0, Guides before the tool 0, after the model 0.

## After dark, the rider says yes: asked once, the resumed pass retried by the gates, sent

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | tool_use draft_plan |
| 2 | u a u | yes | tool_use draft_plan |
| 3 | u a u a u | yes | tool_use Plan |

Outcome: composed by model (sent); 3 model call(s), 3 request(s), 0 rejected by the Converse rules; hook cancels 0, Guides before the tool 2, after the model 0; the rider asked 1 time(s).

## After dark, the rider says no: asked once, the Plan on file, nothing sent

| Request | Turns | Accepted | Model replied |
|---|---|---|---|
| 1 | u | yes | tool_use draft_plan |
| 2 | u a u | yes | tool_use Plan |
| 3 | u a u a u | yes | tool_use Plan |

Outcome: composed by model (held); 3 model call(s), 3 request(s), 0 rejected by the Converse rules; hook cancels 0, Guides before the tool 2, after the model 1; the rider asked 1 time(s).

Turns are the roles in the request, first to last (u user, a assistant). A Guide after the model
discards the assistant turn and appends the reason as a user turn, so the retry after a tool result
has two user turns in a row, and a second Guide makes three. The cap wrapper (`budget.py`) makes
the request sendable before the adapter sees it: the SDK's own neutral assistant turn after the tool
result, ahead of time (the SDK inserts it only after Bedrock has rejected a request once per process
and model id), and adjacent user text turns folded into one (the SDK has no answer for those). The
stand-in enforces the strict reading of the Converse rules; a model that accepts more simply never
rejects, and the passes cost nothing there.
