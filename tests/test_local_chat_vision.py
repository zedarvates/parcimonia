"""Authored image/HTTP fixtures test transport boundaries, not model vision."""

import base64
import binascii
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import struct
import threading
import zlib

import pytest

from tiberium_ai.local_chat import (
    MAX_IMAGE_BYTES, MAX_TEXT_REQUEST_BYTES, _request, chat_completion,
)


def png(width=1, height=1, *, colour=2, depth=8, compressed=True):
    def chunk(name, value):
        content = name + value
        return struct.pack(">I", len(value)) + content + struct.pack(">I", binascii.crc32(content))
    header = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0)
    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    if compressed:
        # Only the default fixture is intended to be a complete valid image.
        raw += chunk(b"IDAT", zlib.compress(b"\x00\x20\x40\x60")) + chunk(b"IEND", b"")
    return raw


def jpeg(width=1, height=1, *, prefix=b""):
    # An authored frame header, without a decoded image-quality claim.
    frame = bytes([8]) + struct.pack(">HH", height, width) + bytes([3, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0])
    return b"\xff\xd8" + prefix + b"\xff\xc0" + struct.pack(">H", len(frame) + 2) + frame + b"\xff\xd9"


def image_part(raw=None, mime="image/png"):
    return {"type": "image_url", "image_url": {"url":
        f"data:{mime};base64," + base64.b64encode(png() if raw is None else raw).decode("ascii")}}


def messages(*parts):
    return [{"role": "user", "content": [
        {"type": "text", "text": "Inspecte ce rendu et signale les incertitudes."},
        *(parts or [image_part()]),
    ]}]


def prepare(value=None, **kwargs):
    return _request("local-vision-fixture", messages() if value is None else value,
                    64, 0, request_schema_version=2, **kwargs)


@contextmanager
def server(*, status=200, response=None):
    calls = []
    response = response or {"model": "local-fixture", "choices": [{
        "message": {"role": "assistant", "content": "Observation de fixture."},
        "finish_reason": "stop",
    }]}
    raw = json.dumps(response).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args):
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=instance.serve_forever,
                              kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}", calls
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=1)


def test_v2_sends_png_and_jpeg_in_one_request_and_returns_only_header_receipts():
    first, second = png(), jpeg(64, 32)
    value = messages(image_part(first), image_part(second, "image/jpeg"))
    with server() as (url, calls):
        result = chat_completion(model="local-vision-fixture", messages=value,
                                 base_url=url, request_schema_version=2)
    assert len(calls) == 1
    assert calls[0]["messages"] == value
    assert set(calls[0]) == {"model", "messages", "max_tokens", "temperature", "stream"}
    assert result["status"] == "completed"
    assert result["schema_version"] == 4
    assert result["request_schema_version"] == 2
    assert result["execution_performed"] is False
    assert result["retries"] == 0
    assert result["images"] == [
        {"message_index": 0, "part_index": i + 1, "mime_type": mime,
         "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
         "width": width, "height": height, "inspection": "container_headers_only"}
        for i, (mime, raw, width, height) in enumerate([
            ("image/png", first, 1, 1), ("image/jpeg", second, 64, 32),
        ])
    ]
    encoded_result = json.dumps(result)
    for part in value[0]["content"][1:]:
        assert part["image_url"]["url"] not in encoded_result
    assert set(result["usage"].values()) == {None}


def test_text_only_v2_and_v1_keep_distinct_output_versions():
    value = [{"role": "user", "content": "Une requête texte."}]
    with server() as (url, calls):
        v1 = chat_completion(model="fixture", messages=value, base_url=url)
        v2 = chat_completion(model="fixture", messages=value, base_url=url,
                             request_schema_version=2)
    assert calls[0] == calls[1]
    assert v1["schema_version"] == 1
    assert "images" not in v1 and "request_schema_version" not in v1
    assert v2["schema_version"] == 4 and v2["images"] == []


def test_embedded_images_require_explicit_v2():
    with pytest.raises(ValueError):
        _request("fixture", messages(), 64, 0)


@pytest.mark.parametrize("version", [True, False, 0, 3, "2", None])
def test_version_is_strict(version):
    with pytest.raises(ValueError):
        _request("fixture", messages(), 64, 0, request_schema_version=version)


@pytest.mark.parametrize("url", [
    "https://example.com/private.png", "http://127.0.0.1/private.png",
    "file:///private.png", "data:image/gif;base64,R0lGODlh",
    "data:image/webp;base64,AAAA", "data:image/png,raw-data",
    "data:image/png;base64,", "data:image/png;base64,%%%",
    "data:image/png;base64,AA==\n", "data:image/png;base64,AB==",
    "data:image/jpeg;base64," + base64.b64encode(png()).decode(),
    "data:image/png;base64," + base64.b64encode(jpeg()).decode(),
    None, 17, {}, [],
])
def test_bad_or_nonembedded_images_are_refused_before_network(monkeypatch, url):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid input must not open a network connection")
    monkeypatch.setattr("http.client.HTTPConnection", forbidden)
    monkeypatch.setattr("http.client.HTTPSConnection", forbidden)
    part = {"type": "image_url", "image_url": {"url": url}}
    with pytest.raises(ValueError):
        chat_completion(model="fixture", messages=messages(part), request_schema_version=2)


@pytest.mark.parametrize("value", [
    [{"role": "system", "content": [image_part()]}],
    [{"role": "assistant", "content": [image_part()]}],
    [{"role": "user", "content": []}],
    [{"role": "user", "content": [{"type": "text", "text": " "}]}],
    [{"role": "user", "content": [{"type": "text", "text": "ok", "extra": 1}]}],
    [{"role": "user", "content": [{"type": "image_url", "image_url": {
        "url": image_part()["image_url"]["url"], "detail": "auto"}}]}],
    [{"role": "user", "content": [{"type": "input_image", "image_url": "x"}]}],
    [{"role": "user", "content": ["text"]}],
    [{"role": "user", "content": [{"type": "text", "text": "x"}] * 17}],
    messages(image_part(), image_part(), image_part()),
    [{"role": "user", "content": "text", "images": []}],
])
def test_closed_message_shapes_and_budgets(value):
    with pytest.raises(ValueError):
        prepare(value)


@pytest.mark.parametrize("raw", [
    b"", b"not an image", png()[:32], png()[:29] + b"\x00" * 4,
    png(0, 1), png(1, 0), png(4097, 1), png(1, 4097), png(2001, 2000),
    png(colour=1), png(colour=2, depth=1), jpeg(0, 1), jpeg(1, 0),
    jpeg(4097, 1), jpeg(2001, 2000), jpeg()[:-2],
    b"\xff\xd8\xff\xe0\x00\x01\xff\xd9",
    b"\xff\xd8\xff\xe0\xff\xff\xff\xd9",
    b"\xff\xd8\xff\xda\x00\x02\xff\xd9",
])
def test_headers_and_advertised_dimensions_are_checked(raw):
    mime = "image/jpeg" if raw.startswith(b"\xff\xd8") else "image/png"
    with pytest.raises(ValueError):
        prepare(messages(image_part(raw, mime)))


def test_jpeg_metadata_is_length_delimited_before_frame():
    metadata = b"fake-frame-marker:\xff\xc0"
    prefix = b"\xff\xe1" + struct.pack(">H", len(metadata) + 2) + metadata
    with server() as (url, _calls):
        result = chat_completion(model="fixture", messages=messages(
            image_part(jpeg(24, 48, prefix=prefix), "image/jpeg")),
            request_schema_version=2, base_url=url)
    assert result["images"][0]["width"] == 24
    assert result["images"][0]["height"] == 48


def test_image_budget_is_decoded_bytes_and_two_maximum_headers_fit():
    # The padded data is only header-valid; admission does not claim decoding.
    raw = png(compressed=False)
    raw += b"\x00" * (MAX_IMAGE_BYTES - len(raw))
    value = messages(image_part(raw), image_part(raw))
    prepared = prepare(value)
    assert len(prepared) < 6 * 1024 * 1024
    with pytest.raises(ValueError):
        prepare(messages(image_part(raw + b"\x00")))


def test_header_only_inspection_does_not_claim_a_decoded_image():
    raw = png(2000, 2000, compressed=False)
    with server() as (url, _calls):
        result = chat_completion(model="fixture", messages=messages(image_part(raw)),
                                 request_schema_version=2, base_url=url)
    assert result["images"][0]["inspection"] == "container_headers_only"
    assert result["images"][0]["width"] * result["images"][0]["height"] == 4_000_000


def test_text_budget_aggregates_string_messages_and_parts_in_utf8():
    at_limit = [{"role": "system", "content": "x" * (MAX_TEXT_REQUEST_BYTES - 2)},
                {"role": "user", "content": [{"type": "text", "text": "é"}]}]
    prepare(at_limit)
    at_limit[1]["content"][0]["text"] += "x"
    with pytest.raises(ValueError):
        prepare(at_limit)


def test_image_count_is_cumulative_across_messages():
    with pytest.raises(ValueError):
        prepare([*messages(), *messages(), *messages()])


@pytest.mark.parametrize("status,expected", [(302, "redirect_refused"), (401, "http_error")])
def test_vision_transport_errors_keep_receipts_without_retries(status, expected):
    with server(status=status) as (url, calls):
        result = chat_completion(model="fixture", messages=messages(),
                                 request_schema_version=2, base_url=url)
    assert result["status"] == expected
    assert len(calls) == 1 and result["retries"] == 0
    assert result["schema_version"] == 4 and len(result["images"]) == 1
    assert "data:image" not in json.dumps(result)


def test_vision_request_does_not_enable_native_tool_execution():
    response = {"model": "fixture", "choices": [{
        "message": {"role": "assistant", "content": None, "tool_calls": [{
            "function": {"name": "shell", "arguments": "private-command"}}]},
        "finish_reason": "tool_calls",
    }]}
    with server(response=response) as (url, calls):
        result = chat_completion(model="fixture", messages=messages(),
                                 request_schema_version=2, base_url=url)
    assert result["status"] == "unsupported_output"
    assert result["execution_performed"] is False
    assert "private-command" not in json.dumps(result)
    assert len(calls) == 1
