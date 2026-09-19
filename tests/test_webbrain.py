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
