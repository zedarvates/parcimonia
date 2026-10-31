"""The existing worker transports image + retrieval fixtures in one local call."""

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_local_chat_vision import image_part, png, server


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "local_chat_worker.py"
SPEC = importlib.util.spec_from_file_location("vision_worker", SCRIPT)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


def request(**updates):
    value = {
        "schema_version": 2, "task_id": "vision-fixture", "model": "local-fixture",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Compare le rendu aux références citées."},
            image_part(),
        ]}], "max_tokens": 64,
    }
    value.update(updates)
    return value


def run(value, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=json.dumps(value, ensure_ascii=True).encode("ascii"),
        capture_output=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=10,
    )


def test_image_and_existing_context_reach_one_http_post_without_version_collision(tmp_path):
    context = tmp_path / "private-context.txt"
    raw = "[note:fixture] Les oreilles doivent être symétriques.\r\n".encode()
    context.write_bytes(raw)
    original = request()
    with server() as (url, calls):
        completed = run(original, "--base-url", url, "--context-file", str(context))
    assert completed.returncode == 0 and completed.stderr == b""
    output = json.loads(completed.stdout)
    assert output["schema_version"] == 4 and output["request_schema_version"] == 2
    assert output["context"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert output["context"]["freshness"] == "not_assessed"
    assert output["images"][0]["message_index"] == 2
    assert output["images"][0]["sha256"] == hashlib.sha256(png()).hexdigest()
    assert output["execution_performed"] is False and output["retries"] == 0
    assert len(calls) == 1 and calls[0]["messages"][2] == original["messages"][0]
    assert json.loads(calls[0]["messages"][1]["content"])["content"] == raw.decode()
    assert str(context).encode() not in completed.stdout
    assert b"data:image" not in completed.stdout


@pytest.mark.parametrize("rag_status", ["success", "failure"])
def test_real_worker_subprocess_keeps_vision_and_rag_receipts_together(tmp_path, rag_status):
    vault = tmp_path / "vault"
    (vault / "tools").mkdir(parents=True)
    text = "[note:fixture-rag] Corpus rédigé pour ce test."
    engine = vault / "tools" / "rag_dag_engine.py"
    engine.write_text(
        "import sys\n" + (f"print({text!r})\n" if rag_status == "success"
                         else "sys.exit(7)\n"), encoding="utf-8",
    )
    with server() as (url, calls):
        completed = run(request(), "--base-url", url, "--vault-dir", str(vault),
                        "--rag-query", "Question de fixture")
    output = json.loads(completed.stdout)
    assert completed.returncode == (0 if rag_status == "success" else 2)
    assert completed.stderr == b""
    assert output["schema_version"] == 4 and output["request_schema_version"] == 2
    assert output["retrieval"]["attempted"] is True
    assert len(output["images"]) == 1
    assert output["execution_performed"] is False
    assert len(calls) == (1 if rag_status == "success" else 0)
    if rag_status == "success":
        assert output["status"] == "completed"
        assert output["context"]["source"] == "existing_rag_engine"
        assert output["images"][0]["message_index"] == 2
    else:
        assert output["status"] == "retrieval_failed"
        assert output["inference_attempted"] is False
        assert output["images"][0]["message_index"] == 0
        assert "context" not in output
    assert str(vault).encode() not in completed.stdout
    assert text.encode() not in completed.stdout


@pytest.mark.parametrize("finish_reason,expected", [("length", "truncated"),
                                                    ("tool_calls", "unsupported_output")])
def test_model_replies_cannot_execute_or_trigger_a_retry(finish_reason, expected):
    message = {"role": "assistant", "content": "partial fixture"}
    if finish_reason == "tool_calls":
        message["tool_calls"] = [{"function": {"name": "not_a_tool"}}]
    response = {"model": "local-fixture", "choices": [
        {"message": message, "finish_reason": finish_reason},
    ]}
    with server(response=response) as (url, calls):
        completed = run(request(), "--base-url", url)
    output = json.loads(completed.stdout)
    assert completed.returncode == 2 and len(calls) == 1
    assert output["status"] == expected and output["schema_version"] == 4
    assert output["execution_performed"] is False and output["retries"] == 0


@pytest.mark.parametrize("bad_case", ["remote", "image_count", "version", "input_size"])
def test_bad_vision_request_fails_before_retrieval_or_inference(monkeypatch, bad_case):
    value = request()
    if bad_case == "remote":
        value["messages"][0]["content"][1]["image_url"]["url"] = "https://example.invalid/private.png"
    elif bad_case == "image_count":
        value["messages"][0]["content"] += [image_part(), image_part()]
    elif bad_case == "version":
        value["schema_version"] = 1
    encoded = json.dumps(value).encode()
    if bad_case == "input_size":
        encoded += b" " * (worker.MAX_MULTIMODAL_REQUEST_BYTES + 1)
    stdin = io.TextIOWrapper(io.BytesIO(encoded), encoding="utf-8")
    stdout, stderr = io.StringIO(), io.StringIO()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid input must not reach a model or retriever")
    monkeypatch.setattr(worker.sys, "stdin", stdin)
    monkeypatch.setattr(worker.sys, "stdout", stdout)
    monkeypatch.setattr(worker.sys, "stderr", stderr)
    monkeypatch.setattr(worker, "retrieve_context", forbidden)
    monkeypatch.setattr(worker, "chat_completion", forbidden)
    assert worker.main(["--vault-dir", "/private-fixture", "--rag-query", "fixture"]) == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "local completion configuration or input failed\n"


def test_added_context_is_revalidated_against_combined_text_budget(tmp_path):
    context = tmp_path / "context.txt"
    context.write_bytes(b"x" * 16384)
    value = request()
    value["messages"][0]["content"][0]["text"] = "x" * 250000
    with server() as (url, calls):
        completed = run(value, "--base-url", url, "--context-file", str(context))
    assert completed.returncode == 2 and completed.stdout == b"" and calls == []
    assert completed.stderr == b"local completion configuration or input failed\n"
