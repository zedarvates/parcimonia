import importlib.util
import json
import math
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tiberium_ai.local_probe import (
    collect_inventory,
    diagnose_local,
    probe_models,
    write_diagnostic,
)


@contextmanager
def server(body=b'{"data":[{"id":"qwen-test"}]}', *, status=200, delay=0, declared=None, drip=False, drip_headers=False):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.command, self.path))
            if delay:
                time.sleep(delay)
            if drip_headers:
                try:
                    for byte in b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.015)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                return
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "http://192.168.1.47:1234/leak")
            self.send_header("Content-Type", "application/json")
            if declared is not False:
                self.send_header("Content-Length", str(len(body) if declared is None else declared))
            self.end_headers()
            try:
                if drip:
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.015)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
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


def test_get_models_is_read_only_and_never_infers_loaded_state():
    with server() as (url, calls):
        result = probe_models(url)
    assert calls == [("GET", "/v1/models")]
    assert result["status"] == "reachable"
    assert result["model_ids"] == ["qwen-test"]
    assert result["model_count"] == 1
    assert result["inference_ready"] is None
    assert result["loaded_state"] == "not_observed"
    assert result["inference_attempted"] is False
    assert result["latency_ms"] >= 0


def test_v1_base_path_is_normalized():
    with server() as (url, calls):
        result = probe_models(url + "/v1/")
    assert calls == [("GET", "/v1/models")]
    assert result["status"] == "reachable"


def test_localhost_is_pinned_to_loopback_without_hostname_lookup():
    with server() as (url, calls):
        result = probe_models(url.replace("127.0.0.1", "localhost"))
    assert result["status"] == "reachable"
    assert result["origin"].startswith("http://127.0.0.1:")
    assert len(calls) == 1


def test_empty_model_list_does_not_claim_inference_readiness():
    with server(b'{"data":[]}') as (url, _calls):
        result = probe_models(url)
    assert result["status"] == "reachable"
    assert result["model_count"] == 0
    assert result["inference_ready"] is None


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
def test_http_error_never_exposes_body_or_response_headers(status):
    with server(b"secret-token-from-error", status=status) as (url, _calls):
        result = probe_models(url)
    assert result["status"] == "http_error"
    assert result["http_status"] == status
    assert "secret-token" not in json.dumps(result)


def test_redirect_is_never_followed():
    with server(b"", status=302) as (url, calls):
        result = probe_models(url)
    assert calls == [("GET", "/v1/models")]
    assert result["status"] == "redirect_refused"
    assert "192.168.1.47" not in json.dumps(result)


@pytest.mark.parametrize("body", [
    b"not JSON secret", b"\xff", b"null", b'{"data":{}}',
    b'{"data":[{}]}', b'{"data":[{"id":true}]}',
    b'{"data":[{"id":""}]}', b'{"data":[{"id":"a\\nsecret"}]}',
    b'{"data":[{"id":"a"},{"id":"a"}]}', b'{"data":[],"data":[]}',
    b'{"data":[],"extra":NaN}',
])
def test_malformed_body_is_sanitized(body):
    with server(body) as (url, _calls):
        result = probe_models(url)
    assert result["status"] == "invalid_response"
    assert result["model_ids"] == []
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("declared", [None, False])
def test_response_size_cap_applies_with_or_without_content_length(declared):
    with server(b"x" * 1025, declared=declared) as (url, _calls):
        result = probe_models(url, max_response_bytes=1024)
    assert result["status"] == "response_too_large"


def test_header_timeout_is_bounded():
    with server(delay=0.2) as (url, _calls):
        start = time.monotonic()
        result = probe_models(url, timeout=0.04)
        elapsed = time.monotonic() - start
    assert result["status"] == "timeout"
    assert elapsed < 0.18


def test_dripped_body_cannot_reset_total_deadline():
    with server(drip=True) as (url, _calls):
        start = time.monotonic()
        result = probe_models(url, timeout=0.08)
        elapsed = time.monotonic() - start
    assert result["status"] == "timeout"
    assert elapsed < 0.2


def test_dripped_headers_cannot_reset_total_deadline():
    with server(drip_headers=True) as (url, _calls):
        start = time.monotonic()
        result = probe_models(url, timeout=0.08)
        elapsed = time.monotonic() - start
    assert result["status"] == "timeout"
    assert elapsed < 0.2


def test_short_body_is_not_a_complete_response():
    with server(b'{"data":[]}', declared=100) as (url, _calls):
        result = probe_models(url)
    assert result["status"] == "invalid_response"


def test_deep_json_is_a_sanitized_error():
    with server(b"[" * 2000 + b"]" * 2000) as (url, _calls):
        result = probe_models(url)
    assert result["status"] == "invalid_response"


def test_absent_server_is_unreachable_without_exception_details(monkeypatch):
    def refused(*args, **kwargs):
        raise ConnectionRefusedError("fixture private connection error")

    monkeypatch.setattr(socket, "create_connection", refused)
    result = probe_models("http://127.0.0.1:1234", timeout=0.1)
    assert result["status"] == "unreachable"
    assert result["error_type"] == "connection_failed"


@pytest.mark.parametrize("url,allow_lan", [
    ("http://example.com", False), ("http://example.com", True),
    ("http://8.8.8.8", True), ("http://0.0.0.0", True),
    ("http://169.254.169.254", True), ("http://[fe80::1]", True),
    ("http://192.168.1.47:1234", False), ("ftp://127.0.0.1", False),
    ("http://user:secret@127.0.0.1", False),
    ("http://127.0.0.1/?token=secret", False),
    ("http://127.0.0.1/#secret", False), ("http://127.0.0.1/admin", False),
    ("http://127.0.0.1:0", False), ("http://127.0.0.1:99999", False),
    ("http://127.0.0.1\n", False),
])
def test_rejected_origin_never_opens_a_connection(monkeypatch, url, allow_lan):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("network attempted")
    monkeypatch.setattr("http.client.HTTPConnection.connect", forbidden)
    with pytest.raises(ValueError) as exc:
        probe_models(url, allow_lan=allow_lan)
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("value", [True, False, -1, 0, math.nan, math.inf, "3", 61])
def test_invalid_timeouts_fail_before_network(value):
    with pytest.raises(ValueError):
        probe_models(timeout=value)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, 1048577])
def test_invalid_caps_fail_before_network(value):
    with pytest.raises(ValueError):
        probe_models(max_response_bytes=value)


def test_lan_opt_in_is_a_boolean():
    with pytest.raises(ValueError):
        probe_models(allow_lan="yes")


def test_inventory_commands_are_fixed_and_stderr_is_never_recorded(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("shutil.which", lambda name: f"/trusted/{name}")
    def run(arguments, **kwargs):
        calls.append(arguments)
        assert kwargs["capture_output"] is True
        assert "shell" not in kwargs
        if arguments[0].endswith("nvidia-smi"):
            return subprocess.CompletedProcess(arguments, 0, "NVIDIA RTX 3060, 12288, 9000, 560.1\n", "secret stderr")
        return subprocess.CompletedProcess(arguments, 0, "lms 0.4.1\n", "secret stderr")
    monkeypatch.setattr("subprocess.run", run)
    result = collect_inventory(tmp_path)
    assert result["scope"] == "caller_machine_only"
    assert result["nvidia"]["gpus"][0]["memory_free_mib"] == 9000
    assert result["lms_cli"]["version"] == "0.4.1"
    assert "secret" not in json.dumps(result)
    assert calls == [
        ["/trusted/nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"],
        ["/trusted/lms", "--version"],
    ]


def test_missing_commands_are_unknown_not_fake_hardware(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    result = collect_inventory(tmp_path)
    assert result["nvidia"] == {"status": "not_installed", "gpus": []}
    assert result["lms_cli"] == {"status": "not_installed", "version": None}
    assert result["hailo"] == "not_inspected"


def test_bad_gpu_output_is_not_an_inventory(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: f"/trusted/{name}")
    monkeypatch.setattr("subprocess.run", lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, "GPU, NaN, 99, driver", "secret"))
    result = collect_inventory(tmp_path)
    assert result["nvidia"] == {"status": "unparseable", "gpus": []}


def test_report_is_versioned_and_separates_remote_endpoint_from_caller_inventory(monkeypatch):
    monkeypatch.setattr("tiberium_ai.local_probe.collect_inventory", lambda _path: {"scope": "caller_machine_only"})
    with server() as (url, _calls):
        report = diagnose_local(url)
    assert report["kind"] == "local-diagnostic"
    assert report["schema_version"] == 1
    assert report["inference_attempted"] is False
    assert report["saving_claim"] is False
    assert "caller" in " ".join(report["limits"])


def test_exclusive_writer_is_private_and_refuses_symlinks(tmp_path):
    target = tmp_path / "diagnostic.json"
    write_diagnostic(target, {"safe": True})
    assert json.loads(target.read_text()) == {"safe": True}
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_diagnostic(target, {"safe": False})
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        write_diagnostic(link, {})
    assert json.loads(target.read_text()) == {"safe": True}


def load_cli():
    path = Path(__file__).resolve().parents[1] / "examples/eurekai_diagnostic.py"
    spec = importlib.util.spec_from_file_location("eurekai_diagnostic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_success_has_a_compact_truthful_summary(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiberium_ai.local_probe.collect_inventory", lambda _path: {"scope": "caller_machine_only"})
    cli = load_cli()
    target = tmp_path / "diagnostic.json"
    with server() as (url, calls):
        assert cli.main(["--base-url", url, "--out", str(target)]) == 0
    assert len(calls) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["inference_ready"] is None
    assert summary["inference_attempted"] is False
    assert json.loads(target.read_text())["endpoint"]["status"] == "reachable"


def test_cli_refuses_existing_output_without_request(monkeypatch, tmp_path, capsys):
    target = tmp_path / "exists.json"
    target.write_text("unchanged")
    cli = load_cli()
    monkeypatch.setattr(cli, "diagnose_local", lambda *_args, **_kwargs: pytest.fail("probe attempted"))
    assert cli.main(["--out", str(target)]) == 2
    assert target.read_text() == "unchanged"
    assert "overwrite" in capsys.readouterr().err


def test_cli_bad_url_does_not_echo_credentials(tmp_path, capsys):
    target = tmp_path / "absent.json"
    assert load_cli().main(["--base-url", "http://user:secret@localhost", "--out", str(target)]) == 2
    captured = capsys.readouterr()
    assert "secret" not in captured.err + captured.out
    assert not target.exists()
