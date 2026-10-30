import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "local_chat_worker", ROOT / "examples" / "local_chat_worker.py",
)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


def request(**updates):
    value = {
        "schema_version": 1, "task_id": "local-code-draft", "model": "local-test",
        "messages": [{"role": "user", "content": "Propose une fonction."}],
    }
    value.update(updates)
    return value


def result(status="completed"):
    return {
        "kind": "local_completion", "schema_version": 1,
        "origin": "http://127.0.0.1:1234", "requested_model": "local-test",
        "response_model": "local-test", "status": status, "content": "candidate",
        "finish_reason": "length" if status == "truncated" else "stop",
        "http_status": 200, "error_type": None, "latency_ms": 1.25,
        "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        "inference_attempted": True, "execution_performed": False, "retries": 0,
    }


class LocalChatWorkerTests(unittest.TestCase):
    def invoke(self, value=None, *, raw=None, argv=(), response=None, error=None):
        if raw is None:
            raw = json.dumps(request() if value is None else value).encode("utf-8")
        stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with (patch.object(worker.sys, "stdin", stdin),
              patch.object(worker.sys, "stdout", stdout),
              patch.object(worker.sys, "stderr", stderr),
              patch.object(worker, "chat_completion", return_value=response or result(),
                           side_effect=error) as client):
            code = worker.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue(), client

    def assert_input_rejected(self, **kwargs):
        code, stdout, stderr, client = self.invoke(**kwargs)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "local completion configuration or input failed\n")
        client.assert_not_called()

    def test_valid_request_calls_client_once_and_writes_one_compact_response(self):
        value = request(max_tokens=48, temperature=0.25)
        code, stdout, stderr, client = self.invoke(
            value, argv=("--base-url", "http://192.168.1.10:1234/v1", "--allow-lan", "--timeout", "90"),
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(len(stdout.splitlines()), 1)
        self.assertNotIn('\": ', stdout)
        self.assertEqual(json.loads(stdout), {**result(), "task_id": value["task_id"]})
        client.assert_called_once_with(
            model="local-test", messages=value["messages"],
            base_url="http://192.168.1.10:1234/v1", allow_lan=True, timeout=90.0,
            max_tokens=48, temperature=0.25,
        )

    def test_defaults_are_explicit(self):
        code, _, _, client = self.invoke()
        self.assertEqual(code, 0)
        client.assert_called_once_with(
            model="local-test", messages=request()["messages"],
            base_url="http://127.0.0.1:1234", allow_lan=False, timeout=180.0,
            max_tokens=1024, temperature=0.0,
        )

    def test_unknown_fields_cannot_override_endpoint_or_execute_tools(self):
        for name, value in (
            ("base_url", "https://secret.invalid"), ("allow_lan", True),
            ("timeout", 10), ("tools", []), ("command", "secret-command"),
        ):
            with self.subTest(name=name):
                self.assert_input_rejected(value=request(**{name: value}))

    def test_truncated_and_failed_responses_are_not_retried(self):
        for status in ("truncated", "timeout", "http_error", "unsupported_output"):
            with self.subTest(status=status):
                code, stdout, stderr, client = self.invoke(response=result(status))
                self.assertEqual(code, 2)
                self.assertEqual(stderr, "")
                self.assertEqual(json.loads(stdout)["status"], status)
                self.assertEqual(json.loads(stdout)["retries"], 0)
                self.assertFalse(json.loads(stdout)["execution_performed"])
                client.assert_called_once()

    def test_invalid_input_never_calls_client(self):
        for value in (
            [], {}, request(schema_version=True), request(schema_version=2),
            request(task_id=""), request(task_id=" a"), request(task_id="x" * 257),
            request(task_id="secret\nvalue"), request(model=""), request(messages=[]),
            request(messages=[{"role": "tool", "content": "secret"}]),
            request(messages=[{"role": "user", "content": "secret", "tool_calls": []}]),
            request(max_tokens=True), request(max_tokens=8193), request(temperature=3),
        ):
            with self.subTest(value=value):
                self.assert_input_rejected(value=value)

    def test_strict_json_and_utf8_are_required(self):
        for raw in (
            b"secret prompt", b"\xff", b'{"schema_version":1,"schema_version":1}',
            json.dumps(request()).replace('"local-test"', 'NaN').encode(),
            b"[" * 2000 + b"]" * 2000,
        ):
            with self.subTest(raw=raw[:50]):
                self.assert_input_rejected(raw=raw)

    def test_input_limit_accepts_exact_boundary_and_rejects_one_more_byte(self):
        encoded = json.dumps(request()).encode()
        padded = encoded + b" " * (worker.MAX_REQUEST_BYTES - len(encoded))
        code, _, _, client = self.invoke(raw=padded)
        self.assertEqual(code, 0)
        client.assert_called_once()
        self.assert_input_rejected(raw=padded + b" ")

    def test_limit_is_measured_in_bytes(self):
        encoded = json.dumps(
            request(messages=[{"role": "user", "content": "é" * 131072}]),
            ensure_ascii=False,
        ).encode("utf-8")
        self.assertGreater(len(encoded), worker.MAX_REQUEST_BYTES)
        self.assert_input_rejected(raw=encoded)

    def test_invalid_process_arguments_are_sanitized(self):
        for argv in (
            ("--timeout", "secret-timeout"), ("--timeout", "nan"),
            ("--base-url", "https://user:secret@127.0.0.1:1234"),
            ("--base-url", "http://192.168.1.10:1234"),
            ("--secret-option", "secret-value"),
        ):
            with self.subTest(argv=argv):
                self.assert_input_rejected(argv=argv)

    def test_client_validation_error_is_sanitized_without_retry(self):
        code, stdout, stderr, client = self.invoke(error=ValueError("secret exception"))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "local completion configuration or input failed\n")
        client.assert_called_once()

    def test_cli_rejects_invalid_input_offline_without_traceback_or_prompt(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        completed = subprocess.run(
            [sys.executable, str(ROOT / "examples" / "local_chat_worker.py")],
            input=b'{"secret-prompt":"do not echo me"}', capture_output=True,
            env=env, cwd=ROOT, timeout=5, check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(completed.stderr, b"local completion configuration or input failed\n")


if __name__ == "__main__":
    unittest.main()
