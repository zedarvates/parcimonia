"""Bounded opt-in native-process capture, without a shell or unbounded pipes.

The deadline covers execution and pipe draining. Cleanup has at most a further
0.25 seconds of waiting. POSIX children start a new session for best-effort
process-group cleanup; Windows cleanup targets the direct child only. This is
not an OS sandbox, authorization gate or guarantee against escaped descendants.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from typing import Any, BinaryIO

__all__ = ["run_bounded"]

_MAX_CAPTURE_BYTES = 1024 * 1024
_CLEANUP_GRACE_SECONDS = 0.25
_POLL_SECONDS = 0.01


def _string(value: Any, label: str, maximum: int, *, empty: bool = False) -> None:
    if type(value) is not str or (not empty and not value) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be a UTF-8 string without NUL, at most {maximum} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8 text.") from exc


def _validate(
    argv: Any, deadline: Any, max_stdout_bytes: Any, max_stderr_bytes: Any,
    cwd: Any, env: Any,
) -> None:
    if type(argv) is not list or not 1 <= len(argv) <= 32:
        raise ValueError("argv must be an array of one to 32 strings.")
    for argument in argv:
        _string(argument, "argv entry", 4096)
    if type(deadline) is not int and type(deadline) is not float:
        raise ValueError("deadline must be a finite monotonic timestamp.")
    try:
        finite = math.isfinite(deadline)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("deadline must be a finite monotonic timestamp.")
    for label, value in (("max_stdout_bytes", max_stdout_bytes), ("max_stderr_bytes", max_stderr_bytes)):
        if type(value) is not int or not 1 <= value <= _MAX_CAPTURE_BYTES:
            raise ValueError(f"{label} must be an integer from 1 to {_MAX_CAPTURE_BYTES}.")
    if cwd is not None:
        _string(cwd, "cwd", 4096)
    if env is not None:
        if type(env) is not dict or len(env) > 512:
            raise ValueError("env must be null or an object of at most 512 strings.")
        size = 0
        for key, value in env.items():
            _string(key, "environment key", 256)
            if "=" in key:
                raise ValueError("Environment keys must not contain '='.")
            _string(value, "environment value", 65536, empty=True)
            size += len(key.encode("utf-8")) + len(value.encode("utf-8")) + 2
            if size > _MAX_CAPTURE_BYTES:
                raise ValueError("The explicit environment exceeds one MiB.")


class _Capture:
    def __init__(self, stream: BinaryIO, maximum: int, stop: threading.Event, wake: threading.Event) -> None:
        self.stream = stream
        self.maximum = maximum
        self.stop = stop
        self.wake = wake
        self.buffer = bytearray()
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.overflow = False
        self.eof = False
        self.error: str | None = None
        self.thread = threading.Thread(target=self._read, daemon=True)

    def _read(self) -> None:
        try:
            while not self.stop.is_set():
                # One lookahead byte distinguishes exact-cap output from an
                # overflow; neither read chunks nor retained buffers are large.
                with self.lock:
                    amount = min(4096, self.maximum - len(self.buffer) + 1)
                chunk = self.stream.read(amount)
                if not chunk:
                    with self.lock:
                        self.eof = True
                    break
                with self.lock:
                    if self.stop.is_set():
                        break
                    remaining = self.maximum - len(self.buffer)
                    self.buffer.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        self.overflow = True
                        break
        except Exception as exc:  # Marshal reader failures, never as valid text.
            if not self.stop.is_set():
                with self.lock:
                    self.error = f"pipe_read_error:{type(exc).__name__}"
        finally:
            try:
                self.stream.close()
            except OSError:
                pass
            self.done.set()
            self.wake.set()

    def snapshot(self) -> tuple[bytes, bool, bool, str | None]:
        with self.lock:
            return bytes(self.buffer), self.eof, self.overflow, self.error

    def state(self) -> tuple[bool, str | None]:
        with self.lock:
            return self.overflow, self.error


def _kill(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            # A direct-child fallback remains useful if group cleanup fails.
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
    elif process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _cleanup(process: subprocess.Popen[bytes], captures: list[_Capture], stop: threading.Event) -> None:
    stop.set()
    _kill(process)
    until = time.monotonic() + _CLEANUP_GRACE_SECONDS
    try:
        process.wait(timeout=max(0.0, until - time.monotonic()))
    except subprocess.TimeoutExpired:
        pass
    for capture in captures:
        # A descendant can keep a pipe open after the direct child exits.
        # Do not block closing a stream owned by a reader on that platform.
        if capture.thread.ident is not None:
            try:
                capture.thread.join(timeout=max(0.0, until - time.monotonic()))
            except RuntimeError:
                # start() can itself have been interrupted before its ready
                # handshake. Preserve the original exception during cleanup.
                pass
        else:
            # If starting a reader failed, nobody owns this pipe's cleanup.
            try:
                capture.stream.close()
            except OSError:
                pass
    if not captures:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def run_bounded(
    argv: list[str], *, deadline: float,
    max_stdout_bytes: int = 262144, max_stderr_bytes: int = 32768,
    cwd: str | None = None, env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run one caller-selected command under an absolute monotonic deadline.

    ``completed`` means the process finished, including nonzero exits; consumers
    must additionally require returncode zero, no error and complete streams.
    Timeout/overflow captures are prefixes only. A rare pipe-read error is
    recorded with incomplete streams and is never a successful transport.
    """
    started_at = time.monotonic()
    _validate(argv, deadline, max_stdout_bytes, max_stderr_bytes, cwd, env)

    def result(status: str, *, process=None, captures=None, error=None):
        samples = [capture.snapshot() for capture in captures] if captures else [(b"", False, False, None)] * 2
        successful_transport = status == "completed" and error is None
        return {
            "status": status,
            "returncode": process.returncode if process is not None else None,
            "stdout": samples[0][0], "stderr": samples[1][0],
            "stdout_complete": successful_transport and samples[0][1] and not samples[0][2] and samples[0][3] is None,
            "stderr_complete": successful_transport and samples[1][1] and not samples[1][2] and samples[1][3] is None,
            "started": process is not None, "error": error,
            "elapsed_ms": max(0.0, (time.monotonic() - started_at) * 1000.0),
        }

    if time.monotonic() >= deadline:
        return result("timeout")
    try:
        process = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False, bufsize=0, cwd=cwd,
            env=dict(env) if env is not None else None,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        return result("failed_to_start", error=type(exc).__name__)

    stop, wake = threading.Event(), threading.Event()
    captures: list[_Capture] = []
    try:
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("Captured process pipes were not created.")
        captures = [
            _Capture(process.stdout, max_stdout_bytes, stop, wake),
            _Capture(process.stderr, max_stderr_bytes, stop, wake),
        ]
        for capture in captures:
            capture.thread.start()
        while True:
            states = [capture.state() for capture in captures]
            if any(state[0] for state in states):
                status, error = "output_limit", None
                break
            errors = [state[1] for state in states if state[1] is not None]
            if errors:
                status, error = "completed", errors[0]
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status, error = "timeout", None
                break
            if process.poll() is not None and all(capture.done.is_set() for capture in captures):
                status, error = "completed", None
                break
            wake.wait(timeout=min(_POLL_SECONDS, remaining))
            wake.clear()
        if status != "completed" or error is not None:
            _cleanup(process, captures, stop)
        else:
            stop.set()
            process.wait(timeout=0)
        return result(status, process=process, captures=captures, error=error)
    except BaseException:
        _cleanup(process, captures, stop)
        raise
