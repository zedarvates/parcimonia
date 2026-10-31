"""Force capture completion between flag inspection and child polling."""

import subprocess
import threading
from types import SimpleNamespace

import pytest

from tiberium_ai import local_retrieval


@pytest.mark.parametrize("failure", ["stdout_overflow", "stderr_overflow", "read_error"])
def test_capture_failure_at_child_exit_never_exposes_context(tmp_path, monkeypatch, failure):
    vault = tmp_path / "vault"
    engine = vault / "tools" / "rag_dag_engine.py"
    engine.parent.mkdir(parents=True)
    stdout = b"x" * 17 if failure == "stdout_overflow" else b"valid"
    stderr = b"x" * 4097 if failure == "stderr_overflow" else b""
    engine.write_text(
        f"import sys\nsys.stdout.buffer.write({stdout!r})\n"
        f"sys.stderr.buffer.write({stderr!r})\n",
        encoding="utf-8",
    )

    original_popen = subprocess.Popen
    release_capture = threading.Event()
    children = []

    class CoordinatedPipe:
        def __init__(self, pipe, *, gated=False, fail_after_first_read=False):
            self.pipe = pipe
            self.gated = gated
            self.fail_after_first_read = fail_after_first_read
            self.reads = 0
            self.reader = None
            self.closed = threading.Event()

        def read1(self, size):
            self.reader = threading.current_thread()
            if self.gated and not release_capture.wait(timeout=5):
                raise OSError("capture coordination timed out")
            if self.fail_after_first_read and self.reads:
                raise OSError("authored capture failure after partial output")
            self.reads += 1
            return self.pipe.read1(size)

        def close(self):
            try:
                self.pipe.close()
            finally:
                self.closed.set()

    class CoordinatedProcess:
        def __init__(self, process):
            self.process = process
            self.stdout = CoordinatedPipe(
                process.stdout,
                gated=failure != "stderr_overflow",
                fail_after_first_read=failure == "read_error",
            )
            self.stderr = CoordinatedPipe(
                process.stderr, gated=failure == "stderr_overflow"
            )

        def __getattr__(self, name):
            return getattr(self.process, name)

        def poll(self):
            # retrieve_context has already inspected both failure flags. Let
            # the pending failure occur, then finish both drains before poll
            # returns, without relying on scheduler timing or sleeps.
            release_capture.set()
            for pipe in (self.stdout, self.stderr):
                assert pipe.closed.wait(timeout=5)
                assert pipe.reader is not None
                pipe.reader.join(timeout=5)
                assert not pipe.reader.is_alive()
            return self.process.wait(timeout=5)

    def coordinated_popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        children.append(process)
        return CoordinatedProcess(process)

    monkeypatch.setattr(local_retrieval.subprocess, "Popen", coordinated_popen)
    try:
        result = local_retrieval.retrieve_context(
            vault, "capture regression", max_output_bytes=16, timeout=10
        )
    finally:
        release_capture.set()
        for process in children:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)

    expected = "capture_failed" if failure == "read_error" else "output_too_large"
    assert result["error_type"] == expected
    assert result["status"] == ("failed" if failure == "read_error" else expected)
    assert result["content"] is None
    assert result["returncode"] == 0
    assert len(children) == 1
    assert result["stdout_bytes_captured"] == len(stdout)


def test_slow_source_revalidation_keeps_timely_command_completed(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    engine = vault / "tools" / "rag_dag_engine.py"
    engine.parent.mkdir(parents=True)
    engine.write_text("print('valid context', end='')\n", encoding="utf-8")

    original_time = local_retrieval.time
    original_hash = local_retrieval._engine_hash
    offset = 0.0
    hash_calls = 0
    clock_observations = []
    timeout = 10.0

    def monotonic():
        observed = original_time.monotonic() + offset
        clock_observations.append(observed)
        return observed

    def hash_with_slow_revalidation(path):
        nonlocal offset, hash_calls
        hash_calls += 1
        if hash_calls == 2:
            # The real command and drains have already completed. Advance only
            # the adapter's clock to simulate expensive source-file I/O.
            assert monotonic() - clock_observations[0] < timeout
            offset = 2 * timeout
        return original_hash(path)

    monkeypatch.setattr(
        local_retrieval, "time",
        SimpleNamespace(monotonic=monotonic, sleep=original_time.sleep),
    )
    monkeypatch.setattr(local_retrieval, "_engine_hash", hash_with_slow_revalidation)

    result = local_retrieval.retrieve_context(vault, "source timing", timeout=timeout)

    assert hash_calls == 2
    assert result["status"] == "completed"
    assert result["error_type"] is None
    assert result["content"] == "valid context"
    assert result["returncode"] == 0
    assert result["engine_sha256_before"] == result["engine_sha256_after"]
    assert result["latency_ms"] >= 2 * timeout * 1000
