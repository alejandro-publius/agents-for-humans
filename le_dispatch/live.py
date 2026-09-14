"""The live path's one retry layer, priced.

Two layers retry a throttled Bedrock call unless told otherwise. botocore's own client (its default
"legacy" retry mode) sends the request up to five times with a random backoff of up to 1, 2, 4 and 8
seconds, and neither the trace nor the budget sees those requests; only then does the ThrottlingException
reach Strands, whose ModelRetryStrategy (six attempts, waits of 4, 8, 16, 32 and 64 seconds by default)
retries the whole thing. Stacked, one model call under a sustained throttle is thirty requests and about
two and a half minutes, of which the budget counts six and the trace shows six. The wire evidence
("a throttle retried: 3 calls") was measured with the stand-in client, which has no botocore layer, so
it priced the Strands layer alone.

The live path therefore runs on one layer: botocore's is switched off (one request per attempt, the
"standard" mode with `total_max_attempts` 1; `max_attempts` 1 would still be two requests) and Strands'
is bounded (four attempts, waits of 2, 4 and 8 seconds) so every retry is one the trace shows, the
budget counts and the wire priced, and a throttled model call costs at most four requests and fourteen
seconds. A read timeout of sixty seconds bounds a hung stream (the adapter raises, the delivery layer
composes the plan in code, the rider still gets one). Every live construction of the adapter goes
through `model()`: the runtime entrypoint, `make demo-live`, `make eval-live`, and the wire's stand-ins,
so the client the evidence was produced on is configured like the client the laptop will run.
"""

from __future__ import annotations

from typing import Any

ATTEMPTS = 4  # Strands' layer: the first request and three retries on a throttle
INITIAL_DELAY = 2  # seconds; doubles per retry, capped at MAX_DELAY
MAX_DELAY = 8
READ_TIMEOUT = 60  # seconds a stream may stay silent before the adapter raises
CONNECT_TIMEOUT = 5
CLIENT_RETRIES = {"total_max_attempts": 1, "mode": "standard"}  # botocore's layer: off


def waits() -> list[int]:
    """The seconds Strands waits before each retry under the live strategy."""
    out: list[int] = []
    delay = INITIAL_DELAY
    for _ in range(ATTEMPTS - 1):
        out.append(delay)
        delay = min(delay * 2, MAX_DELAY)
    return out


def worst_case() -> dict[str, Any]:
    """What one model call can cost on the live path, in requests and seconds, before the delivery layer
    composes the plan in code: a sustained throttle, or a hung stream."""
    return {
        "attempts": ATTEMPTS,
        "waits_seconds": waits(),
        "throttled_requests": ATTEMPTS,  # one request per attempt: botocore's layer sends no more
        "throttled_seconds": sum(waits()),
        "hung_seconds": READ_TIMEOUT,  # a read timeout is not a throttle: no retry, code composes
        "client_retries": dict(CLIENT_RETRIES),
        "read_timeout": READ_TIMEOUT,
        "connect_timeout": CONNECT_TIMEOUT,
    }


def describe() -> str:
    w = worst_case()
    waits_text = ", ".join(f"{s} s" for s in w["waits_seconds"])
    return (
        f"live retries: botocore's layer off (one request per attempt), Strands' bounded to {w['attempts']} "
        f"attempts (waits {waits_text}): a throttled model call costs at most {w['throttled_requests']} requests "
        f"and {w['throttled_seconds']} s; a hung stream {w['hung_seconds']} s, then code composes the plan"
    )


def client_config() -> Any:
    """The botocore Config every live Bedrock client is built with."""
    from botocore.config import Config

    return Config(retries=dict(CLIENT_RETRIES), read_timeout=READ_TIMEOUT, connect_timeout=CONNECT_TIMEOUT)


def retry_strategy() -> Any:
    """Strands' ModelRetryStrategy with the live bounds; `Agent(retry_strategy=...)` via build_agent."""
    from strands.event_loop._retry import ModelRetryStrategy

    return ModelRetryStrategy(max_attempts=ATTEMPTS, initial_delay=INITIAL_DELAY, max_delay=MAX_DELAY)


def model(model_id: str, region: str, **kwargs: Any) -> Any:
    """A BedrockModel on the live client configuration (built without credentials; the call needs them)."""
    from strands.models import BedrockModel

    return BedrockModel(model_id=model_id, region_name=region, boto_client_config=client_config(), **kwargs)


def client_is_live_configured(client: Any) -> bool:
    """Does this bedrock-runtime client carry the live configuration? (What a test checks on every path.)"""
    config = client.meta.config
    return dict(config.retries or {}) == CLIENT_RETRIES and config.read_timeout == READ_TIMEOUT
