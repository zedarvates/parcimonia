import pytest

from tiberium_ai.adapters import (
    completion_text,
    completion_tokens,
    resources_from_completion,
)


def payload(**usage_overrides):
    usage = {
        "prompt_tokens": 15,
        "completion_tokens": 8,
        "total_tokens": 23,
        "completion_tokens_details": {"reasoning_tokens": 7},
    }
    usage.update(usage_overrides)
    return {
        "choices": [{"message": {"role": "assistant", "content": "OK"}}],
        "usage": usage,
    }


def test_total_tokens_are_read_from_the_usage_block():
    assert completion_tokens(payload()) == 23


def test_resources_carry_tokens_and_leave_the_rest_unknown():
    vector = resources_from_completion(payload())
    assert vector.tokens == 23
    assert vector.latency_ms is None
    assert vector.vram_mb is None
    assert vector.energy_joules is None


@pytest.mark.parametrize("broken", [
    {"usage": None},
    {"usage": {"total_tokens": -1}},
    {"usage": {"total_tokens": True}},
    {"usage": {"total_tokens": "23"}},
    {"usage": {"total_tokens": 23, "prompt_tokens": 15, "completion_tokens": 9}},
])
def test_malformed_usage_is_rejected(broken):
    with pytest.raises((TypeError, ValueError)):
        completion_tokens(broken)


def test_a_response_without_usage_is_rejected():
    with pytest.raises(ValueError, match="usage"):
        completion_tokens({"choices": []})


def test_message_content_is_returned_verbatim():
    assert completion_text(payload()) == "OK"


def test_an_empty_answer_is_returned_as_an_empty_string():
    empty = payload()
    empty["choices"][0]["message"]["content"] = ""
    assert completion_text(empty) == ""


@pytest.mark.parametrize("broken", [
    {"choices": []},
    {"choices": "none"},
    {"choices": [{"message": {"content": 1}}]},
    {"choices": [{"message": None}]},
])
def test_malformed_choices_are_rejected(broken):
    with pytest.raises((TypeError, ValueError)):
        completion_text(broken)
