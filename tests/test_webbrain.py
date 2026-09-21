import pytest

from tiberium_ai.contracts import Task
from tiberium_ai.resources import ResourceVector
from tiberium_ai.webbrain import (
    WebBrainMode,
    WebBrainRequest,
    WebBrainResponse,
    build_webbrain_request,
    parse_webbrain_response,
)


def test_build_webbrain_request_ask():
    task = Task("t_web", "web_query", {"prompt": "Find pricing table on this page"})
    req = build_webbrain_request(task, mode=WebBrainMode.ASK)
    assert req.tool_name == "webbrain_run"
    assert req.arguments["task"] == "Find pricing table on this page"
    assert req.arguments["mode"] == "ask"


def test_build_webbrain_request_extract():
    task = Task("t_web", "extract", {"prompt": "Extract products"})
    schema = {"type": "object", "properties": {"price": {"type": "number"}}}
    req = build_webbrain_request(task, schema=schema)
    assert req.tool_name == "webbrain_extract"
    assert req.arguments["schema"] == schema


def test_build_webbrain_request_high_risk_act_forbidden():
    task = Task("t_web", "web_payment", {"prompt": "Click pay"}, risk_class="high")
    with pytest.raises(ValueError, match="forbidden on risk class 'high'"):
        build_webbrain_request(task, mode=WebBrainMode.ACT)


def test_parse_webbrain_response():
    payload = {
        "run_id": "wb_12345",
        "status": "completed",
        "content": "Found 3 pricing tiers: Free, Pro, Enterprise.",
        "steps_taken": 4,
        "extracted_data": {"tiers": ["Free", "Pro", "Enterprise"]},
        "usage": {"total_tokens": 850},
    }
    resp = parse_webbrain_response(payload)
    assert resp.run_id == "wb_12345"
    assert resp.status == "completed"
    assert resp.steps_taken == 4
    assert resp.tokens_used == 850
    assert resp.extracted_data == {"tiers": ["Free", "Pro", "Enterprise"]}

    vector = resp.to_resource_vector(latency_ms=1250.0)
    assert isinstance(vector, ResourceVector)
    assert vector.tokens == 850
    assert vector.latency_ms == 1250.0


def test_parse_webbrain_response_validation():
    with pytest.raises(TypeError, match="payload must be a mapping"):
        parse_webbrain_response("not-a-mapping")

    with pytest.raises(ValueError, match="must contain a nonempty string 'run_id'"):
        parse_webbrain_response({"content": "hello"})

    with pytest.raises(ValueError, match="steps_taken must be a nonnegative integer"):
        parse_webbrain_response({"run_id": "x", "steps_taken": -1})


def test_webbrain_client_convenience():
    from tiberium_ai.webbrain import WebBrainClient
    client = WebBrainClient()
    task = Task("t_client", "query", {"prompt": "Check status"})
    cmd = client.build_command(task)
    assert cmd.tool_name == "webbrain_run"
    assert cmd.arguments["task"] == "Check status"

    resp = client.parse_result({
        "run_id": "wb_99",
        "status": "completed",
        "content": "Done",
        "steps_taken": 1,
        "usage": {"total_tokens": 120},
    })
    assert resp.run_id == "wb_99"
    assert resp.tokens_used == 120


def _payload():
    return {
        "run_id": "wb_round",
        "status": "completed",
        "content": "Read the pricing table only.",
        "steps_taken": 2,
        "usage": {"total_tokens": 42},
    }


def test_round_trip_ask_uses_the_injected_transport_without_acting():
    from tiberium_ai.webbrain import WebBrainClient, WebBrainMode

    seen = {}

    def transport(endpoint_url, command):
        seen["endpoint_url"] = endpoint_url
        seen["command"] = command
        return _payload()

    client = WebBrainClient()
    task = Task("t_rt", "web_query", {"prompt": "Read the pricing table"})
    result = client.round_trip(task, transport=transport)

    assert result.status == "ok"
    assert result.mode is WebBrainMode.ASK
    assert result.response is not None
    assert result.response.run_id == "wb_round"
    assert result.detail_code == "completed"
    assert result.performed is True
    assert seen["endpoint_url"] == "ws://127.0.0.1:17374/extension"
    assert seen["command"]["arguments"]["mode"] == "ask"
    assert seen["command"]["tool_name"] == "webbrain_run"


@pytest.mark.parametrize("mode", [WebBrainMode.ACT, WebBrainMode.DEV])
def test_round_trip_refuses_act_and_dev(mode):
    from tiberium_ai.webbrain import WebBrainClient

    client = WebBrainClient()
    task = Task("t_rt", "web_query", {"prompt": "Click pay"})
    with pytest.raises(ValueError, match="ASK only"):
        client.round_trip(task, mode=mode, transport=lambda url, command: _payload())


def test_round_trip_refuses_a_non_loopback_endpoint():
    from tiberium_ai.webbrain import WebBrainClient

    client = WebBrainClient(endpoint_url="ws://example.com:17374/extension")
    task = Task("t_rt", "web_query", {"prompt": "Read"})
    with pytest.raises(ValueError, match="loopback"):
        client.round_trip(task, transport=lambda url, command: _payload())


def test_round_trip_without_a_transport_is_unavailable():
    from tiberium_ai.webbrain import WebBrainClient

    client = WebBrainClient()
    task = Task("t_rt", "web_query", {"prompt": "Read"})
    result = client.round_trip(task)

    assert result.status == "unavailable"
    assert result.detail_code == "no_transport_configured"
    assert result.response is None
    assert result.performed is False


@pytest.mark.parametrize("error", [ConnectionRefusedError, TimeoutError])
def test_round_trip_reports_an_absent_endpoint_as_unavailable(error):
    from tiberium_ai.webbrain import WebBrainClient

    def transport(endpoint_url, command):
        raise error("nothing listening")

    client = WebBrainClient()
    task = Task("t_rt", "web_query", {"prompt": "Read"})
    result = client.round_trip(task, transport=transport)

    assert result.status == "unavailable"
    assert result.detail_code == f"transport_unavailable:{error.__name__}"
    assert result.response is None


def test_round_trip_reports_a_transport_failure_as_error():
    from tiberium_ai.webbrain import WebBrainClient

    def transport(endpoint_url, command):
        raise ValueError("protocol broke")

    client = WebBrainClient()
    task = Task("t_rt", "web_query", {"prompt": "Read"})
    result = client.round_trip(task, transport=transport)

    assert result.status == "error"
    assert result.detail_code == "transport_error:ValueError"
    assert result.response is None


def test_round_trip_reports_an_unparseable_payload_as_error():
    from tiberium_ai.webbrain import WebBrainClient

    client = WebBrainClient()
    task = Task("t_rt", "web_query", {"prompt": "Read"})
    result = client.round_trip(task, transport=lambda url, command: {"content": "no id"})

    assert result.status == "error"
    assert result.detail_code == "invalid_response"
    assert result.response is None


def test_round_trip_result_can_carry_a_measured_vector():
    from tiberium_ai.webbrain import WebBrainClient

    client = WebBrainClient()
    task = Task("t_rt", "web_query", {"prompt": "Read"})
    result = client.round_trip(task, transport=lambda url, command: _payload())
    vector = result.to_resource_vector(latency_ms=900.0)
    assert vector.tokens == 42
    assert vector.latency_ms == 900.0
