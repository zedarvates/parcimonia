"""One explicit local text inference; replies remain data for the existing caller.

No retry, model management, tool execution, cloud fallback or implicit history.
LM Studio may JIT-load the explicitly requested model on this POST.
"""

from __future__ import annotations

import http.client
import json
import math
import socket
import ssl
import threading
import time
from typing import Any

from .local_probe import _endpoint, _positive_number, _reject_constant, _unique_object


def _identifier(value: object) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("model must be a nonempty identifier of at most 256 characters.")
    return value


def _request(model: str, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> bytes:
    _identifier(model)
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
        raise ValueError("max_tokens must be an integer in [1, 8192].")
    if (type(temperature) not in (int, float) or not 0 <= temperature <= 2
            or not math.isfinite(temperature)):
        raise ValueError("temperature must be finite and in [0, 2].")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
        raise ValueError("messages must contain between 1 and 32 text messages.")
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in ("system", "user", "assistant")
                or not isinstance(message["content"], str) or not message["content"].strip()):
            raise ValueError("messages require only a supported role and nonempty text content.")
    data = json.dumps({
        "model": model, "messages": messages, "max_tokens": max_tokens,
        "temperature": temperature, "stream": False,
    }, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(data) > 262144:
        raise ValueError("request exceeds 262144 UTF-8 bytes.")
    return data


def _response(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(payload, dict):
        raise ValueError("response must be an object.")
    response_model = payload.get("model")
    if response_model is not None:
        _identifier(response_model)
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("response must contain exactly one choice.")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("response must contain an assistant message.")
    if message.get("tool_calls") or message.get("function_call") or choice.get("finish_reason") == "tool_calls":
        return {"status": "unsupported_output", "error_type": "tool_calls_not_supported",
                "response_model": response_model}
    reason, content = choice.get("finish_reason"), message.get("content")
    if reason not in ("stop", "length") or not isinstance(content, str) or not content.strip():
        raise ValueError("response must contain finished nonempty text.")
    usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    supplied = payload.get("usage")
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise ValueError("usage must be an object when supplied.")
        for name in usage:
            value = supplied.get(name)
            if value is not None and (type(value) is not int or not 0 <= value <= 2**53 - 1):
                raise ValueError("token counts must be nonnegative safe integers or unknown.")
            usage[name] = value
        if all(value is not None for value in usage.values()):
            if usage["prompt_tokens"] + usage["completion_tokens"] != usage["total_tokens"]:
                raise ValueError("token counts are inconsistent.")
    return {
        "status": "completed" if reason == "stop" else "truncated", "error_type": None,
        "response_model": response_model, "content": content, "finish_reason": reason, "usage": usage,
    }


def chat_completion(
    *, model: str, messages: list[dict[str, str]],
    base_url: str = "http://127.0.0.1:1234", allow_lan: bool = False,
    max_tokens: int = 1024, temperature: float = 0.0, timeout: float = 180.0,
    max_response_bytes: int = 1048576,
) -> dict[str, Any]:
    """Perform at most one POST with an absolute I/O deadline and bounded body.

    Validation precedes connection. Literal private addresses require allow_lan.
    The result records server-reported usage only; missing usage stays unknown.
    Timeout does not prove that inference stopped on the server. No automatic
    fallback or retry is performed, including after uncertain delivery.
    """
    timeout = _positive_number(timeout, "timeout", 600)
    if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 4194304:
        raise ValueError("max_response_bytes must be an integer in [1, 4194304].")
    scheme, host, port, origin = _endpoint(base_url, allow_lan)
    data = _request(model, messages, max_tokens, temperature)
    result: dict[str, Any] = {
        "kind": "local_completion", "schema_version": 1, "origin": origin,
        "requested_model": model, "response_model": None, "status": "unreachable",
        "content": None, "finish_reason": None, "http_status": None, "error_type": None,
        "latency_ms": None,
        "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        "inference_attempted": False, "execution_performed": False, "retries": 0,
    }
    started = time.monotonic()
    deadline = started + timeout
    connection = None
    watchdog = None
    expired = threading.Event()
    try:
        if scheme == "https":
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
            connection.sock = socket.create_connection(
                (host, port), timeout=max(0.000001, deadline - time.monotonic()),
            )
            # Defer TLS handshake until the deadline watchdog can interrupt it.
            connection.sock = context.wrap_socket(
                connection.sock, server_hostname=host, do_handshake_on_connect=False,
            )
        else:
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
            connection.connect()
        sock = connection.sock
        assert sock is not None

        def expire() -> None:
            expired.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        # Interrupt slow header/body streams as well as ordinary socket stalls.
        watchdog = threading.Timer(max(0, deadline - time.monotonic()), expire)
        watchdog.daemon = True
        watchdog.start()
        sock.settimeout(max(0.000001, deadline - time.monotonic()))
        if scheme == "https":
            sock.do_handshake()
        sock.settimeout(max(0.000001, deadline - time.monotonic()))
        result["inference_attempted"] = True
        connection.request("POST", "/v1/chat/completions", body=data, headers={
            "Content-Type": "application/json", "Accept": "application/json",
        })
        sock.settimeout(max(0.000001, deadline - time.monotonic()))
        response = connection.getresponse()
        result["http_status"] = response.status
        if 300 <= response.status < 400:
            result.update(status="redirect_refused", error_type="redirect_refused")
            return result
        if response.status != 200:
            result.update(status="http_error", error_type="http_error")
            return result
        length = response.getheader("Content-Length")
        declared = None if length is None else int(length)
        if declared is not None and declared < 0:
            raise ValueError("invalid content length.")
        if declared is not None and declared > max_response_bytes:
            result.update(status="response_too_large", error_type="response_too_large")
            return result
        body = bytearray()
        while not response.isclosed():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            sock.settimeout(remaining)
            chunk = response.read1(min(65536, max_response_bytes + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > max_response_bytes:
                result.update(status="response_too_large", error_type="response_too_large")
                return result
        if declared is not None and len(body) != declared:
            raise ValueError("incomplete response.")
        if time.monotonic() >= deadline:
            raise TimeoutError
        result.update(_response(bytes(body)))
    except (socket.timeout, TimeoutError):
        result.update(status="timeout", error_type="timeout")
    except (UnicodeError, ValueError, TypeError, RecursionError, http.client.HTTPException):
        error = "timeout" if expired.is_set() else "invalid_response"
        result.update(status=error, error_type=error)
    except OSError:
        result.update(status="timeout" if expired.is_set() else "unreachable",
                      error_type="timeout" if expired.is_set() else "connection_failed")
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if connection is not None:
            connection.close()
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
    return result
