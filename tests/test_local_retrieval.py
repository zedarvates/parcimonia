"""Exercise local retrieval only against authored, temporary Python engines."""

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest

from tiberium_ai import local_retrieval


REQUIRED_FIELDS = {
    "kind", "schema_version", "status", "content", "engine_sha256_before",
    "engine_sha256_after", "query_sha256", "top", "latency_ms", "returncode",
    "error_type", "stdout_bytes_captured", "attempted",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def test_reader_start_failure_reaps_the_direct_child(engine, processes, monkeypatch):
    vault, _script = engine("import time\ntime.sleep(5)\n")
    def unavailable_thread(*_args, **_kwargs):
        raise RuntimeError("cannot start a new thread")
    monkeypatch.setattr(local_retrieval.threading.Thread, "start", unavailable_thread)
    result = local_retrieval.retrieve_context(vault, "Question de test.", timeout=0.1)
    assert result["status"] == "failed"
    assert result["content"] is None
    assert result["error_type"] == "capture_unavailable"
    assert len(processes) == 1 and processes[0][2].poll() is not None
    assert processes[0][2].stdout.closed and processes[0][2].stderr.closed


@pytest.fixture
def engine(tmp_path):
    def create(source):
        vault = tmp_path / "coffre local avec espaces"
        script = vault / "tools" / "rag_dag_engine.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(textwrap.dedent(source), encoding="utf-8")
        return vault, script

    return create


@pytest.fixture
def processes(monkeypatch):
    """Record and clean up only main processes created by the function under test."""
    original = subprocess.Popen
    calls = []

    def recording_popen(*args, **kwargs):
        process = original(*args, **kwargs)
        calls.append((args, kwargs, process))
        return process

    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    if hasattr(local_retrieval, "Popen"):
        monkeypatch.setattr(local_retrieval, "Popen", recording_popen)
    yield calls
    for _args, _kwargs, process in calls:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)


def assert_record(result, *, query, top, status, attempted=True):
    assert REQUIRED_FIELDS <= result.keys()
    assert result["kind"] == "local_retrieval"
    assert result["schema_version"] == 1
    assert result["status"] == status
    assert result["query_sha256"] == digest(query.encode("utf-8"))
    assert result["top"] == top
    assert result["attempted"] is attempted
    assert isinstance(result["latency_ms"], (int, float))
    assert not isinstance(result["latency_ms"], bool)
    assert math.isfinite(result["latency_ms"])
    assert result["latency_ms"] >= 0
    assert isinstance(result["stdout_bytes_captured"], int)
    assert 0 <= result["stdout_bytes_captured"] <= 16385
    if status == "completed":
        assert result["error_type"] is None
        assert result["returncode"] == 0
        assert isinstance(result["content"], str)
    else:
        assert result["content"] is None
        assert isinstance(result["error_type"], str)
        assert result["error_type"]


def assert_unchanged_engine(result, script):
    expected = digest(script.read_bytes())
    assert result["engine_sha256_before"] == expected
    assert result["engine_sha256_after"] == expected


def test_one_documented_command_uses_exact_arguments_and_vault_cwd(engine, processes):
    query = "Où est l'été ? 'citation' ; $(commande) & contexte"
    vault, script = engine('''
        import json
        import os
        import sys

        sys.stdout.write(json.dumps({
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "texte": "Contexte français : été, forêt et cœur."
        }, ensure_ascii=False, sort_keys=True))
    ''')
    result = local_retrieval.retrieve_context(
        vault, query, top=4, python_executable=sys.executable
    )
    expected = json.dumps({
        "argv": [str(script), "rag", "--query", query, "--top", "4"],
        "cwd": str(vault),
        "texte": "Contexte français : été, forêt et cœur.",
    }, ensure_ascii=False, sort_keys=True)

    assert_record(result, query=query, top=4, status="completed")
    assert result["content"] == expected
    assert result["stdout_bytes_captured"] == len(expected.encode("utf-8"))
    assert_unchanged_engine(result, script)
    assert len(processes) == 1
    args, kwargs, process = processes[0]
    command = args[0] if args else kwargs["args"]
    assert command == [sys.executable, str(script), "rag", "--query", query, "--top", "4"]
    assert Path(kwargs["cwd"]) == vault
    assert kwargs.get("shell", False) is False
    assert process.poll() == 0


def test_default_python_and_top_preserve_exact_french_text(engine, processes):
    content = "\n  Résultat français : façade, forêt, cœur.\n\n"
    vault, script = engine(f"import sys\nsys.stdout.buffer.write({content.encode('utf-8')!r})\n")

    result = local_retrieval.retrieve_context(vault, "façade")

    assert_record(result, query="façade", top=3, status="completed")
    assert result["content"] == content
    assert result["stdout_bytes_captured"] == len(content.encode("utf-8"))
    assert_unchanged_engine(result, script)
    assert len(processes) == 1
    args, kwargs, _process = processes[0]
    command = args[0] if args else kwargs["args"]
    assert command[0] == sys.executable


def test_timeout_returns_promptly_and_reaps_the_main_process(engine, processes):
    vault, script = engine("import time\ntime.sleep(10)\n")
    started = time.monotonic()

    result = local_retrieval.retrieve_context(vault, "lent", timeout=0.15)

    assert time.monotonic() - started < 3
    assert_record(result, query="lent", top=3, status="timeout")
    assert_unchanged_engine(result, script)
    assert len(processes) == 1
    assert processes[0][2].poll() is not None


def test_oversized_stdout_is_bounded_and_never_exposed(engine, processes):
    vault, script = engine('''
        import sys
        sys.stdout.buffer.write(b"private-output-" * 100000)
        sys.stdout.buffer.flush()
    ''')

    result = local_retrieval.retrieve_context(vault, "grand", max_output_bytes=128)

    assert_record(result, query="grand", top=3, status="output_too_large")
    assert result["stdout_bytes_captured"] <= 129
    assert "private-output" not in json.dumps(result)
    assert_unchanged_engine(result, script)
    assert len(processes) == 1
    assert processes[0][2].poll() is not None


def test_oversized_stderr_is_bounded_and_never_exposed(engine, processes):
    vault, script = engine('''
        import sys
        sys.stderr.buffer.write(b"private-diagnostic-" * 100000)
        sys.stderr.buffer.flush()
    ''')

    result = local_retrieval.retrieve_context(vault, "diagnostic")

    assert_record(result, query="diagnostic", top=3, status="output_too_large")
    assert result["stdout_bytes_captured"] == 0
    assert "private-diagnostic" not in json.dumps(result)
    assert_unchanged_engine(result, script)
    assert len(processes) == 1
    assert processes[0][2].poll() is not None


def test_nonzero_exit_discards_stdout_stderr_and_traceback(engine):
    vault, script = engine('''
        import sys
        sys.stdout.write("private stdout context")
        sys.stderr.write("Traceback: private traceback with secret-token")
        sys.exit(7)
    ''')

    result = local_retrieval.retrieve_context(vault, "échec")

    assert_record(result, query="échec", top=3, status="failed")
    assert result["returncode"] == 7
    serialized = json.dumps(result)
    assert "private" not in serialized
    assert "secret-token" not in serialized
    assert "Traceback" not in serialized
    assert_unchanged_engine(result, script)


@pytest.mark.parametrize("output", [b"", b"\xff\xfeprivate-content"])
def test_empty_or_invalid_utf8_output_is_rejected_without_content(engine, output):
    vault, script = engine(f"import sys\nsys.stdout.buffer.write({output!r})\n")

    result = local_retrieval.retrieve_context(vault, "format")

    assert_record(result, query="format", top=3, status="invalid_output")
    assert result["returncode"] == 0
    assert "private-content" not in json.dumps(result)
    assert_unchanged_engine(result, script)


def test_engine_change_during_execution_blocks_otherwise_valid_content(engine):
    vault, script = engine('''
        from pathlib import Path
        import sys

        path = Path(__file__)
        with path.open("a", encoding="utf-8") as target:
            target.write("\\n# moteur modifié pendant la recherche\\n")
        sys.stdout.write("private context from changed engine")
    ''')
    before = digest(script.read_bytes())

    result = local_retrieval.retrieve_context(vault, "provenance")

    assert_record(result, query="provenance", top=3, status="source_changed")
    assert result["engine_sha256_before"] == before
    assert result["engine_sha256_after"] == digest(script.read_bytes())
    assert result["engine_sha256_after"] != before
    assert "private context" not in json.dumps(result)


def test_missing_engine_is_unavailable_without_launch(tmp_path, processes):
    vault = tmp_path / "coffre sans moteur"
    vault.mkdir()

    result = local_retrieval.retrieve_context(vault, "absent")

    assert_record(result, query="absent", top=3, status="unavailable", attempted=False)
    assert result["engine_sha256_before"] is None
    assert result["engine_sha256_after"] is None
    assert result["returncode"] is None
    assert result["stdout_bytes_captured"] == 0
    assert processes == []


@pytest.mark.parametrize("query", [None, 42, b"texte", "", " \t\n ", "x" * 4097, "é" * 2049])
def test_invalid_queries_are_rejected_before_popen(engine, monkeypatch, query):
    vault, _script = engine("print('unused')\n")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("retrieval launched for invalid query")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    if hasattr(local_retrieval, "Popen"):
        monkeypatch.setattr(local_retrieval, "Popen", forbidden)
    with pytest.raises((TypeError, ValueError)):
        local_retrieval.retrieve_context(vault, query)


@pytest.mark.parametrize("name,value", [
    ("top", True), ("top", False), ("top", 0), ("top", -1),
    ("top", 11), ("top", 1.0), ("top", "3"), ("top", None),
    ("timeout", True), ("timeout", False), ("timeout", 0), ("timeout", -0.1),
    ("timeout", 120.1), ("timeout", math.inf), ("timeout", math.nan),
    ("timeout", "1"), ("timeout", None),
    ("max_output_bytes", True), ("max_output_bytes", False),
    ("max_output_bytes", 0), ("max_output_bytes", -1),
    ("max_output_bytes", 16385), ("max_output_bytes", 128.0),
    ("max_output_bytes", "128"), ("max_output_bytes", None),
])
def test_invalid_options_are_rejected_before_popen(engine, monkeypatch, name, value):
    vault, _script = engine("print('unused')\n")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("retrieval launched for invalid option")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    if hasattr(local_retrieval, "Popen"):
        monkeypatch.setattr(local_retrieval, "Popen", forbidden)
    with pytest.raises((TypeError, ValueError)):
        local_retrieval.retrieve_context(vault, "valide", **{name: value})


@pytest.mark.parametrize("query,top,max_output_bytes", [
    ("é" * 2048, 1, 1),
    ("x" * 4096, 10, 16384),
])
def test_inclusive_query_top_and_output_size_boundaries(engine, query, top, max_output_bytes):
    vault, script = engine(f"import sys\nsys.stdout.buffer.write(b'x' * {max_output_bytes})\n")

    result = local_retrieval.retrieve_context(
        vault, query, top=top, max_output_bytes=max_output_bytes, timeout=120
    )

    assert_record(result, query=query, top=top, status="completed")
    assert result["content"] == "x" * max_output_bytes
    assert result["stdout_bytes_captured"] == max_output_bytes
    assert_unchanged_engine(result, script)
