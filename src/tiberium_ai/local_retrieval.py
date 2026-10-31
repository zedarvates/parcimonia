"""Bound one explicitly configured existing RAG command; never build an index.

This adapter is not a sandbox. The caller must qualify the chosen vault script
and its permissions. The documented command is fixed, but its implementation
and any imported code still belong to that external installation.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time
from typing import Any

from .local_probe import _positive_number


def _engine_hash(path: Path) -> str:
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("engine must be a regular file.")
        raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise ValueError("engine source exceeds the inspection limit.")
    return hashlib.sha256(raw).hexdigest()


def retrieve_context(
    vault_dir: str | Path, query: str, *, top: int = 3, timeout: float = 15.0,
    python_executable: str | Path | None = None, max_output_bytes: int = 16384,
) -> dict[str, Any]:
    """Run one fixed rag query command without a shell.

    Binary pipes preserve the exact UTF-8 output. Captures use bounded buffers,
    including one sentinel byte, and stderr is never returned. The timeout covers
    the command and pipe collection, with a bounded cleanup allowance. Source
    reads and OS process creation are not preemptible here; the caller also owns
    the whole worker's deadline. Only the direct child is killed on failure.
    """
    timeout = _positive_number(timeout, "timeout", 120)
    if (not isinstance(query, str) or not query.strip() or query != query.strip()
            or "\0" in query or len(query.encode("utf-8")) > 4096):
        raise ValueError("query must be trimmed nonempty UTF-8 text within 4096 bytes.")
    if type(top) is not int or not 1 <= top <= 10:
        raise ValueError("top must be an integer in [1, 10].")
    if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 16384:
        raise ValueError("max_output_bytes must be an integer in [1, 16384].")
    if not isinstance(vault_dir, (str, Path)) or not str(vault_dir).strip():
        raise ValueError("vault_dir must be an explicit local directory.")
    executable = sys.executable if python_executable is None else os.fspath(python_executable)
    if (not isinstance(executable, str) or not executable
            or executable != executable.strip()
            or any(ord(c) < 32 for c in executable)):
        raise ValueError("python_executable must name one trusted executable.")
    vault = Path(vault_dir).resolve()
    engine = vault / "tools" / "rag_dag_engine.py"
    result: dict[str, Any] = {
        "kind": "local_retrieval", "schema_version": 1, "status": "unavailable",
        "content": None, "engine_sha256_before": None, "engine_sha256_after": None,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "top": top, "latency_ms": None, "returncode": None,
        "error_type": None, "stdout_bytes_captured": 0, "attempted": False,
    }
    started = time.monotonic()
    try:
        if not vault.is_dir():
            raise OSError
        result["engine_sha256_before"] = _engine_hash(engine)
    except (OSError, ValueError):
        result.update(error_type="source_unavailable", latency_ms=round((time.monotonic() - started) * 1000, 3))
        return result

    output = bytearray()
    overflow, read_error = threading.Event(), threading.Event()
    readers: list[threading.Thread] = []
    owned_pipes: list[Any] = []
    process = None
    completed_at = None

    def drain(pipe: Any, *, keep: bool, limit: int) -> None:
        captured = 0
        try:
            while True:
                chunk = pipe.read1(min(4096, limit + 1 - captured))
                if not chunk:
                    break
                captured += len(chunk)
                if keep:
                    output.extend(chunk)
                if captured > limit:
                    overflow.set()
                    break
        except (OSError, ValueError):
            read_error.set()
        finally:
            pipe.close()

    try:
        deadline = time.monotonic() + timeout
        result["attempted"] = True
        process = subprocess.Popen(
            [executable, str(engine), "rag", "--query", query, "--top", str(top)],
            cwd=vault, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        for pipe, keep, limit in ((process.stdout, True, max_output_bytes),
                                  (process.stderr, False, 4096)):
            reader = threading.Thread(
                target=drain, args=(pipe,), kwargs={"keep": keep, "limit": limit}, daemon=True,
            )
            reader.start()
            readers.append(reader)
            owned_pipes.append(pipe)
        while True:
            if overflow.is_set():
                result.update(status="output_too_large", error_type="output_too_large")
                break
            if read_error.is_set():
                result.update(status="failed", error_type="capture_failed")
                break
            if process.poll() is not None and all(not thread.is_alive() for thread in readers):
                completed_at = time.monotonic()
                if process.returncode == 0:
                    result.update(status="completed")
                else:
                    result.update(status="failed", error_type="process_failed")
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result.update(status="timeout", error_type="timeout")
                break
            time.sleep(min(0.005, remaining))
    except OSError:
        result.update(status="unavailable", error_type="process_unavailable")
    except RuntimeError:
        result.update(status="failed", error_type="capture_unavailable")
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                result.update(status="failed", error_type="cleanup_incomplete")
            result["returncode"] = process.returncode
            for pipe in (process.stdout, process.stderr):
                if pipe is not None and pipe not in owned_pipes:
                    pipe.close()
        # A descendant could hold a pipe open. Do not block closing a buffered
        # reader owned by its thread; the caller owns any process-tree cleanup.
        for reader in readers:
            reader.join(timeout=0.1)
        result["stdout_bytes_captured"] = len(output)
        try:
            result["engine_sha256_after"] = _engine_hash(engine)
        except (OSError, ValueError):
            pass
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 3)

    if result["status"] == "completed":
        # Readers can signal overflow between the loop's first flag check and
        # its process/EOF check. Reconcile after the readers have finished.
        if overflow.is_set() or len(output) > max_output_bytes:
            result.update(status="output_too_large", error_type="output_too_large")
        elif read_error.is_set() or any(reader.is_alive() for reader in readers):
            result.update(status="failed", error_type="capture_failed")
        elif completed_at is None or completed_at >= deadline:
            result.update(status="timeout", error_type="timeout")
        elif result["engine_sha256_before"] != result["engine_sha256_after"]:
            result.update(status="source_changed", error_type="source_changed")
        else:
            try:
                text = bytes(output).decode("utf-8")
                if not text.removeprefix("\ufeff").strip():
                    raise ValueError
                result["content"] = text
            except (UnicodeError, ValueError):
                result.update(status="invalid_output", error_type="invalid_output")
    return result
