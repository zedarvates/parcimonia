import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tiberium_ai.local_chat import chat_completion


MESSAGES = [{"role": "user", "content": "Vérifie ce calcul / check this calculation."}]


def reply(**changes):
    value = {"model": "observed-alias", "choices": [{
        "message": {"role": "assistant", "content": "Réponse / answer"},
        "finish_reason": "stop",
    }]}
    value.update(changes)
    return value


@contextmanager
def server(payload=None, *, raw=None, status=200, declared=None, drip=False):
    data = raw if raw is not None else json.dumps(reply() if payload is None else payload).encode()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append((self.command, self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "http://192.168.1.47:1234/other")
            if declared is not False:
                self.send_header("Content-Length", str(len(data) if declared is None else declared))
            self.end_headers()
            try:
                if drip:
                    for byte in data:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.015)
                else:
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}", calls
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=1)


def call(url, **kwargs):
    return chat_completion(model="requested-id", messages=MESSAGES, base_url=url, **kwargs)


def test_single_post_records_text_actual_model_and_only_reported_usage(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    with server(reply(usage={"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11})) as (url, calls):
        result = call(url + "/v1/")
    assert len(calls) == 1
    method, path, body = calls[0]
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert body == {"model": "requested-id", "messages": MESSAGES, "max_tokens": 1024, "temperature": 0, "stream": False}
    assert result["requested_model"] == "requested-id"
    assert result["response_model"] == "observed-alias"
    assert result["status"] == "completed"
    assert result["content"] == "Réponse / answer"
    assert result["usage"]["total_tokens"] == 11
    assert result["inference_attempted"] is True
    assert result["execution_performed"] is False
    assert result["retries"] == 0
    assert result["latency_ms"] >= 0


def test_absent_usage_is_unknown_not_zero_or_derived():
    with server() as (url, _calls):
        result = call(url)
    assert result["status"] == "completed"
    assert set(result["usage"].values()) == {None}


def test_length_is_truncated_and_not_reported_as_success():
    value = reply()
    value["choices"][0]["finish_reason"] = "length"
    with server(value) as (url, calls):
        result = call(url)
    assert result["status"] == "truncated"
    assert result["content"]
    assert result["finish_reason"] == "length"
    assert len(calls) == 1


def test_tool_calls_are_never_returned_for_execution():
    value = reply()
    value["choices"][0]["message"]["tool_calls"] = [{"function": {"name": "shell", "arguments": "secret-command"}}]
    value["choices"][0]["finish_reason"] = "tool_calls"
    with server(value) as (url, calls):
        result = call(url)
    assert result["status"] == "unsupported_output"
    assert result["content"] is None
    assert "secret-command" not in json.dumps(result)
    assert result["execution_performed"] is False
    assert len(calls) == 1


@pytest.mark.parametrize("status,expected", [(302, "redirect_refused"), (401, "http_error"), (503, "http_error")])
def test_http_errors_and_redirects_do_not_leak_bodies_or_retry(status, expected):
    with server(raw=b"private-error-body", status=status) as (url, calls):
        result = call(url)
    assert result["status"] == expected
    assert result["http_status"] == status
    assert len(calls) == 1
    assert "private-error-body" not in json.dumps(result)
    assert "192.168.1.47" not in json.dumps(result)


@pytest.mark.parametrize("raw", [
    b'{"choices":[]}', b'null', b'not-json-secret', b'\xff',
    b'{"choices":[],"choices":[]}', b'{"x":NaN}',
    json.dumps(reply(usage={"total_tokens": -1})).encode(),
    json.dumps(reply(usage={"total_tokens": True})).encode(),
    json.dumps(reply(usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 1})).encode(),
    json.dumps(reply(model=17)).encode(),
])
def test_malformed_response_fails_without_returning_unverified_content(raw):
    with server(raw=raw) as (url, calls):
        result = call(url)
    assert result["status"] == "invalid_response"
    assert result["content"] is None
    assert len(calls) == 1


@pytest.mark.parametrize("declared", [False, 100000])
def test_response_size_limit_handles_declared_and_streamed_bodies(declared):
    with server(declared=declared) as (url, _calls):
        result = call(url, max_response_bytes=20)
    assert result["status"] == "response_too_large"


def test_incomplete_body_is_not_a_usable_completion():
    with server(declared=100000) as (url, _calls):
        result = call(url)
    assert result["status"] == "invalid_response"
    assert result["content"] is None


def test_slow_stream_stops_at_deadline_without_retry():
    with server(drip=True) as (url, calls):
        started = time.monotonic()
        result = call(url, timeout=0.08)
        elapsed = time.monotonic() - started
    assert result["status"] == "timeout"
    assert len(calls) == 1
    assert elapsed < 0.8
    assert result["retries"] == 0


@pytest.mark.parametrize("override", [
    {"model": ""}, {"model": " model "}, {"model": "x\nsecret"},
    {"messages": []}, {"messages": [{"role": "tool", "content": "x"}]},
    {"messages": [{"role": "user", "content": "x", "tool_calls": []}]},
    {"messages": [{"role": "user", "content": "x" * 262144}]},
    {"messages": MESSAGES * 33}, {"max_tokens": True}, {"max_tokens": 8193},
    {"temperature": float("nan")}, {"temperature": True}, {"temperature": 10**400},
    {"timeout": 0}, {"timeout": 10**400},
    {"base_url": "https://example.com"}, {"base_url": "http://192.168.1.47:1234"},
    {"base_url": "http://user:secret@localhost:1234"}, {"max_response_bytes": 0},
])
def test_bad_configuration_never_opens_a_connection(monkeypatch, override):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("network must not be used")
    monkeypatch.setattr("http.client.HTTPConnection", forbidden)
    monkeypatch.setattr("http.client.HTTPSConnection", forbidden)
    arguments = {"model": "requested-id", "messages": MESSAGES, **override}
    with pytest.raises((TypeError, ValueError)):
        chat_completion(**arguments)


def test_connection_failure_is_known_only_as_a_failed_attempt():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    result = call(f"http://127.0.0.1:{port}", timeout=0.1)
    assert result["status"] == "unreachable"
    assert result["content"] is None
    assert result["retries"] == 0


@pytest.mark.parametrize("reason,exit_code", [("stop", 0), ("length", 2)])
def test_worker_cli_reaches_the_explicit_endpoint_and_returns_attributed_json(reason, exit_code):
    root = Path(__file__).resolve().parents[1]
    value = reply()
    value["choices"][0]["finish_reason"] = reason
    environment = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONIOENCODING": "ascii"}
    with server(value) as (url, calls):
        result = subprocess.run(
            [sys.executable, str(root / "examples/local_chat_worker.py"), "--base-url", url],
            input=json.dumps({"schema_version": 1, "task_id": "code-local-1",
                              "model": "requested-id", "messages": MESSAGES}),
            capture_output=True, text=True, encoding="utf-8", env=environment, timeout=5,
        )
    assert result.returncode == exit_code, result.stderr
    record = json.loads(result.stdout)
    assert record["task_id"] == "code-local-1"
    assert record["finish_reason"] == reason
    assert record["execution_performed"] is False
    assert len(calls) == 1
