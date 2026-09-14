"""F55: one retry layer on the live path, priced (le_dispatch/live.py)."""

from __future__ import annotations

import importlib.util
import json
import sys

from botocore.awsrequest import AWSResponse
from le_dispatch import live
from le_dispatch.interfaces import ROOT, Trip, fixture_policy

TRIP = Trip(rider_id="r1", origin="DELN", destination="EMBR", outages=("DELN-E1",))


def _throttling_client(config):
    """A real bedrock-runtime client whose HTTP send is replaced (botocore's before-send hook) by a 429
    ThrottlingException; the retry handler runs as it would on the wire, nothing leaves the process."""
    import boto3
    from strands.models import BedrockModel

    session = boto3.Session(aws_access_key_id="test", aws_secret_access_key="test", region_name="us-west-2")
    model = BedrockModel(  # dummy keys: the request must be signable; it never leaves the process
        model_id="us.amazon.nova-lite-v1:0", endpoint_url=live_dead(), boto_client_config=config, boto_session=session
    )
    sends: list[str] = []

    class Raw:
        def __init__(self, data: bytes):
            self._data = data

        def read(self, *args):
            return self._data

        def stream(self, *args, **kwargs):
            yield self._data

    def fake_send(request, **kwargs):
        sends.append(request.url)
        body = json.dumps({"message": "Too many requests, please wait before trying again."}).encode()
        headers = {
            "x-amzn-ErrorType": "ThrottlingException:http://internal.amazon.com/coral/",
            "content-type": "application/json",
        }
        return AWSResponse(request.url, 429, headers, Raw(body))

    model.client.meta.events.register("before-send.bedrock-runtime.ConverseStream", fake_send)
    return model.client, sends


def live_dead() -> str:
    from le_dispatch.bedrock_wire import DEAD_ENDPOINT

    return DEAD_ENDPOINT


def test_botocores_own_retry_layer_is_off_on_the_live_client():
    """The default client retries a throttle itself (legacy mode: five requests, invisible to the budget and
    the trace) before Strands ever sees it; the live configuration sends one request per attempt."""
    import pytest
    from botocore.exceptions import ClientError

    default, default_sends = _throttling_client(None)
    with pytest.raises(ClientError):
        default.converse_stream(modelId="m", messages=[{"role": "user", "content": [{"text": "hi"}]}])
    assert len(default_sends) == 5 and default.meta.config.retries == {"mode": "legacy"}
    assert not live.client_is_live_configured(default)

    client, sends = _throttling_client(live.client_config())
    with pytest.raises(ClientError):
        client.converse_stream(modelId="m", messages=[{"role": "user", "content": [{"text": "hi"}]}])
    assert len(sends) == 1 and live.client_is_live_configured(client)
    assert client.meta.config.read_timeout == live.READ_TIMEOUT and client.meta.config.connect_timeout == 5


def test_strands_layer_is_bounded_and_the_arithmetic_is_pinned():
    """Four attempts with waits of 2, 4 and 8 seconds: a throttled model call costs at most four requests and
    fourteen seconds; a hung stream sixty seconds. The strategy object carries the same numbers, and the
    description a judge reads on `make preflight` is derived from them."""
    from strands.event_loop._retry import ModelRetryStrategy

    strategy = live.retry_strategy()
    assert isinstance(strategy, ModelRetryStrategy)
    assert (strategy._max_attempts, strategy._initial_delay, strategy._max_delay) == (4, 2, 8)
    w = live.worst_case()
    assert w["waits_seconds"] == [2, 4, 8] and w["throttled_seconds"] == 14 and w["throttled_requests"] == 4
    assert w["hung_seconds"] == 60 and w["client_retries"] == {"total_max_attempts": 1, "mode": "standard"}
    text = live.describe()
    assert "4 attempts" in text and "14 s" in text and "60 s" in text and "one request per attempt" in text


def test_the_bounded_layer_through_the_adapter_three_throttles_then_the_plan_and_four_then_code():
    """Through the real BedrockModel with the stand-in client: three throttles then a compliant model reach the
    plan on the fourth attempt (the last the live strategy allows); four throttles exhaust it, the adapter
    raises, and the rider still gets the plan, composed by code."""
    from le_dispatch.bedrock_wire import client_error, compliant_steps, quick_retries, run_wire

    kb, policy = fixture_policy()
    d = policy(TRIP)
    throttle = client_error("ThrottlingException", "Too many requests, please wait before trying again.")
    three = run_wire("three", [throttle] * 3 + compliant_steps(d), kb, policy, TRIP, retry_strategy=quick_retries())
    assert three.outcome.composed_by == "model" and len(three.requests) == 3 + len(compliant_steps(d))
    four = run_wire("four", [throttle] * 4 + compliant_steps(d), kb, policy, TRIP, retry_strategy=quick_retries())
    assert four.outcome.composed_by == "code" and len(four.requests) == 4  # the fifth request is never made
    assert four.outcome.plan is not None and four.outcome.plan["option"] == d.top_option


def test_every_live_construction_is_on_the_live_configuration(monkeypatch):
    """The runtime's model factory, `make demo-live` and `make eval-live` build the model through live.model():
    the client each hands the adapter carries the configuration; and make_runtime puts the bounded
    strategy on every run."""
    ep_spec = importlib.util.spec_from_file_location(
        "entrypoint_live", ROOT / "infra" / "agentcore" / "runtime" / "entrypoint.py"
    )
    ep = importlib.util.module_from_spec(ep_spec)
    ep_spec.loader.exec_module(ep)
    runtime_model = ep.bedrock_model_factory("us.amazon.nova-lite-v1:0", "us-west-2")(TRIP, None)
    assert live.client_is_live_configured(runtime_model.client)

    def load_script(name):
        spec = importlib.util.spec_from_file_location(f"{name}_live_test", ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{name}_live_test"] = module
        spec.loader.exec_module(module)
        return module

    demo = load_script("demo_live")
    assert live.client_is_live_configured(demo.bedrock_model("us.amazon.nova-lite-v1:0", "us-west-2").client)
    ev = load_script("eval_live")

    class M:
        model_id = "us.amazon.nova-lite-v1:0"

    assert live.client_is_live_configured(ev.bedrock_factory("us-west-2")(M()).client)
    # the wire's stand-ins are built the same way (live.model) before their client is replaced
    from le_dispatch import bedrock_wire

    calls: list[str] = []
    original = live.model

    def counting(model_id, region, **kwargs):
        calls.append(model_id)
        return original(model_id, region, **kwargs)

    monkeypatch.setattr(live, "model", counting)
    bedrock_wire.wired_learner_model("us.amazon.nova-lite-v1:0")
    bedrock_wire.wired_model([], "us.amazon.nova-lite-v1:0")
    assert calls == ["us.amazon.nova-lite-v1:0"] * 2
    # make_runtime hands handle() the bounded strategy (checked without the SDK's app: the same default)
    import inspect

    assert "live.retry_strategy()" in inspect.getsource(ep.make_runtime)
