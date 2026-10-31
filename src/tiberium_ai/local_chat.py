"""One explicit local text/vision inference; replies remain data for the caller.

No retry, model management, tool execution, cloud fallback or implicit history.
LM Studio may JIT-load the explicitly requested model on this POST.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import json
import math
import socket
import ssl
import struct
import threading
import time
from typing import Any

from .local_probe import _endpoint, _positive_number, _reject_constant, _unique_object


MAX_TEXT_REQUEST_BYTES = 262144
MAX_VISION_REQUEST_BYTES = 6 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGES = 2
MAX_IMAGE_PIXELS = 4_000_000
MAX_IMAGE_AXIS = 4096


def _image_header(raw: bytes, mime_type: str) -> tuple[int, int]:
    """Observe dimensions in a PNG/JPEG header, without decoding image pixels.

    Header checks bound advertised dimensions and catch obvious MIME mismatches.
    They do not establish a valid complete compressed stream or a safe decoder.
    """
    if mime_type == "image/png":
        if (len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n"
                or raw[8:16] != b"\x00\x00\x00\rIHDR"):
            raise ValueError("image does not contain a supported PNG header.")
        if binascii.crc32(raw[12:29]) != int.from_bytes(raw[29:33], "big"):
            raise ValueError("invalid PNG header checksum.")
        width, height = struct.unpack(">II", raw[16:24])
        # PNG permits only these colour-type/bit-depth combinations.
        depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                  4: (8, 16), 6: (8, 16)}
        if (raw[25] not in depths or raw[24] not in depths[raw[25]]
                or raw[26] != 0 or raw[27] != 0 or raw[28] not in (0, 1)):
            raise ValueError("unsupported PNG header parameters.")
        return width, height
    if len(raw) < 4 or raw[:2] != b"\xff\xd8" or raw[-2:] != b"\xff\xd9":
        raise ValueError("image does not contain a supported JPEG header.")
    # Inspect length-delimited metadata up to the first frame/scan. Compressed
    # entropy data is deliberately left to the explicitly selected runtime.
    position = 2
    frame_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while position < len(raw) - 2:
        if raw[position] != 0xFF:
            raise ValueError("invalid JPEG header marker.")
        while position < len(raw) and raw[position] == 0xFF:
            position += 1
        if position >= len(raw):
            break
        marker = raw[position]
        position += 1
        if marker in (0x00, 0xD8, 0xD9, 0xDA) or 0xD0 <= marker <= 0xD7:
            break
        if marker == 0x01:  # Standalone TEM marker.
            continue
        if position + 2 > len(raw):
            break
        length = int.from_bytes(raw[position:position + 2], "big")
        if length < 2 or position + length > len(raw) - 2:
            raise ValueError("invalid JPEG header segment length.")
        if marker in frame_markers:
            if length < 8:
                raise ValueError("invalid JPEG frame header.")
            components = raw[position + 7]
            if (components not in (1, 3, 4) or length != 8 + 3 * components
                    or raw[position + 2] not in (8, 12, 16)):
                raise ValueError("unsupported JPEG frame header.")
            height = int.from_bytes(raw[position + 3:position + 5], "big")
            width = int.from_bytes(raw[position + 5:position + 7], "big")
            return width, height
        position += length
    raise ValueError("JPEG dimensions are unavailable before image data.")


def _embedded_image(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        raise ValueError("image URL must be an embedded PNG or JPEG data URL.")
    mime_type = None
    encoded = None
    for supported in ("image/png", "image/jpeg"):
        prefix = f"data:{supported};base64,"
        if value.startswith(prefix):
            mime_type = supported
            # Reject oversized strings before creating or decoding their copy.
            if len(value) - len(prefix) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
                raise ValueError("embedded image exceeds its byte budget.")
            encoded = value[len(prefix):]
            break
    if encoded is None or mime_type is None:
        raise ValueError("only embedded PNG/JPEG data URLs are supported.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("image requires canonical base64.") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("embedded image exceeds its byte budget.")
    if base64.b64encode(raw).decode("ascii") != encoded:
        raise ValueError("image requires canonical base64.")
    width, height = _image_header(raw, mime_type)
    if (not 1 <= width <= MAX_IMAGE_AXIS or not 1 <= height <= MAX_IMAGE_AXIS
            or width * height > MAX_IMAGE_PIXELS):
        raise ValueError("image header dimensions exceed their pixel budget.")
    return {"mime_type": mime_type, "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw), "width": width, "height": height,
            "inspection": "container_headers_only"}


def _validate_messages(messages: object, request_schema_version: int) -> list[dict[str, Any]]:
    if type(request_schema_version) is not int or request_schema_version not in (1, 2):
        raise ValueError("request_schema_version must be 1 or 2.")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
        raise ValueError("messages must contain between 1 and 32 messages.")
    images = []
    text_bytes = 0
    for message_index, message in enumerate(messages):
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in ("system", "user", "assistant")):
            raise ValueError("messages require only a supported role and content.")
        content = message["content"]
        if isinstance(content, str) and content.strip():
            text_bytes += len(content.encode("utf-8"))
            continue
        if (request_schema_version != 2 or message["role"] != "user"
                or not isinstance(content, list) or not 1 <= len(content) <= 16):
            raise ValueError("only v2 user messages support nonempty content-part lists.")
        for part_index, part in enumerate(content):
            if not isinstance(part, dict):
                raise ValueError("content parts must be objects.")
            if (set(part) == {"type", "text"} and part["type"] == "text"
                    and isinstance(part["text"], str) and part["text"].strip()):
                text_bytes += len(part["text"].encode("utf-8"))
            elif (set(part) == {"type", "image_url"} and part["type"] == "image_url"
                    and isinstance(part["image_url"], dict)
                    and set(part["image_url"]) == {"url"}):
                if len(images) >= MAX_IMAGES:
                    raise ValueError("request exceeds its image-count budget.")
                receipt = _embedded_image(part["image_url"]["url"])
                images.append({"message_index": message_index, "part_index": part_index,
                               **receipt})
            else:
                raise ValueError("unsupported or malformed multimodal content part.")
    if request_schema_version == 2 and text_bytes > MAX_TEXT_REQUEST_BYTES:
        raise ValueError("text content exceeds 262144 UTF-8 bytes.")
    return images


def _identifier(value: object) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("model must be a nonempty identifier of at most 256 characters.")
    return value


def _request(model: str, messages: list[dict[str, Any]], max_tokens: int, temperature: float,
             *, request_schema_version: int = 1) -> bytes:
    _identifier(model)
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
        raise ValueError("max_tokens must be an integer in [1, 8192].")
    if (type(temperature) not in (int, float) or not 0 <= temperature <= 2
            or not math.isfinite(temperature)):
        raise ValueError("temperature must be finite and in [0, 2].")
    _validate_messages(messages, request_schema_version)
    data = json.dumps({
        "model": model, "messages": messages, "max_tokens": max_tokens,
        "temperature": temperature, "stream": False,
    }, ensure_ascii=False, allow_nan=False).encode("utf-8")
    limit = MAX_TEXT_REQUEST_BYTES if request_schema_version == 1 else MAX_VISION_REQUEST_BYTES
    if len(data) > limit:
        raise ValueError(f"request exceeds {limit} UTF-8 bytes.")
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
    *, model: str, messages: list[dict[str, Any]],
    base_url: str = "http://127.0.0.1:1234", allow_lan: bool = False,
    max_tokens: int = 1024, temperature: float = 0.0, timeout: float = 180.0,
    max_response_bytes: int = 1048576,
    request_schema_version: int = 1,
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
    data = _request(model, messages, max_tokens, temperature,
                    request_schema_version=request_schema_version)
    result: dict[str, Any] = {
        "kind": "local_completion", "schema_version": 1, "origin": origin,
        "requested_model": model, "response_model": None, "status": "unreachable",
        "content": None, "finish_reason": None, "http_status": None, "error_type": None,
        "latency_ms": None,
        "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        "inference_attempted": False, "execution_performed": False, "retries": 0,
    }
    if request_schema_version == 2:
        result.update(schema_version=4, request_schema_version=2,
                      images=_validate_messages(messages, request_schema_version))
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
