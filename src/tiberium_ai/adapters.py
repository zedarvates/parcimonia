"""Adapters that turn a provider response into measured resources.

Only parsing lives here: no network, no model and no credentials. The caller
performs the call, hands the response over, and gets back a validated token
count or a resource vector ready for a measurement record.
"""

from __future__ import annotations

from typing import Any, Mapping

from .resources import ResourceVector

__all__ = ["completion_text", "completion_tokens", "resources_from_completion"]


def _usage_block(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("a provider response must be a mapping.")
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        raise ValueError("a provider response must carry a usage block.")
    return usage


def completion_tokens(payload: object) -> int:
    """Return the total token count of one completion."""
    usage = _usage_block(payload)
    total = usage.get("total_tokens")
    if type(total) is not int or total < 0:
        raise ValueError("usage.total_tokens must be a nonnegative integer.")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if (
        type(prompt) is int
        and type(completion) is int
        and prompt + completion != total
    ):
        raise ValueError(
            "usage.prompt_tokens plus usage.completion_tokens must equal total_tokens."
        )
    return total


def resources_from_completion(payload: object) -> ResourceVector:
    """Build a resource vector from a completion payload.

    Tokens come from the usage block; latency is measured by the caller, VRAM
    and energy stay unknown because this API does not report them.
    """
    return ResourceVector(tokens=completion_tokens(payload))


def completion_text(payload: object) -> str:
    """Return the first message content, without inventing an empty answer."""
    if not isinstance(payload, Mapping):
        raise TypeError("a provider response must be a mapping.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("a provider response must carry at least one choice.")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("choices[0] must be a mapping.")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("choices[0].message must be a mapping.")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("choices[0].message.content must be a string.")
    return content
