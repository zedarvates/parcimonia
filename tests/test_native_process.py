"""Real bounded subprocesses; no OCR/model installation is required."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tiberium_ai.native_process import run_bounded


def _python(source: str, *args: str) -> list[str]:
    return [sys.executable, "-c", source, *args]


def _run(source: str, **kwargs):
    return run_bounded(_python(source), deadline=time.monotonic() + 5, **kwargs)


def test_success_captures_both_streams_and_a_finite_measurement():
    result = _run("import os;os.write(1,b'output');os.write(2,b'diagnostic')")
    assert result == dict(result, status="completed", returncode=0, stdout=b"output", stderr=b"diagnostic", stdout_complete=True, stderr_complete=True, started=True, error=None)
    assert type(result["elapsed_ms"]) is float and result["elapsed_ms"] >= 0


def test_utf8_is_preserved_as_bytes_not_repaired_text():
    result = _run("import os;os.write(1,'été'.encode('utf-8'))")
    assert result["stdout"] == "été".encode("utf-8")
    assert type(result["stdout"]) is bytes


def test_nonzero_exit_is_completed_transport_not_success():
    result = _run("import os;os.write(2,b'refused');raise SystemExit(7)")
    assert result["status"] == "completed"
    assert result["returncode"] == 7
    assert result["stderr"] == b"refused"
    assert result["stdout_complete"] and result["stderr_complete"]


def test_stdin_is_closed_to_the_child():
    result = _run("import sys;sys.stdout.write(repr(sys.stdin.buffer.read()))")
    assert result["status"] == "completed"
    assert result["stdout"] == b"b''"


def test_stdout_and_stderr_are_drained_concurrently():
    source = "import os\nfor i in range(64):\n os.write(1,b'a'*2048)\n os.write(2,b'b'*2048)\n"
    result = _run(source, max_stdout_bytes=131072, max_stderr_bytes=131072)
    assert result["status"] == "completed"
    assert result["returncode"] == 0
    assert result["stdout"] == b"a" * 131072
    assert result["stderr"] == b"b" * 131072
    assert result["stdout_complete"] and result["stderr_complete"]


@pytest.mark.parametrize("stream", [1, 2])
def test_exact_capture_cap_is_not_an_overflow(stream):
    result = _run(f"import os;os.write({stream},b'x'*4096)", max_stdout_bytes=4096, max_stderr_bytes=4096)
    assert result["status"] == "completed"
    assert result["stdout_complete"] and result["stderr_complete"]
    assert result["stdout" if stream == 1 else "stderr"] == b"x" * 4096


@pytest.mark.parametrize("stream", [1, 2])
def test_one_lookahead_byte_triggers_a_bounded_prefix(stream):
    result = _run(f"import os;os.write({stream},b'x'*4097)", max_stdout_bytes=4096, max_stderr_bytes=4096)
    assert result["status"] == "output_limit"
    assert result["stdout" if stream == 1 else "stderr"] == b"x" * 4096
    assert result["stdout_complete"] is False and result["stderr_complete"] is False


def test_unbounded_writer_is_stopped_without_retaining_unbounded_output():
    source = "import os\nwhile True:\n os.write(1,b'x'*4096)\n os.write(2,b'y'*4096)\n"
    started = time.monotonic()
    result = _run(source, max_stdout_bytes=8000, max_stderr_bytes=8000)
    assert result["status"] == "output_limit"
    assert len(result["stdout"]) <= 8000 and len(result["stderr"]) <= 8000
    assert result["returncode"] is not None
    assert time.monotonic() - started < 3


def test_timeout_stops_a_sleeping_process():
    started = time.monotonic()
    result = run_bounded(_python("import time;time.sleep(10)"), deadline=started + 0.15)
    assert result["status"] == "timeout"
    assert result["started"] is True
    assert result["returncode"] is not None
    assert result["stdout_complete"] is False and result["stderr_complete"] is False
    assert time.monotonic() - started < 3


def test_deadline_covers_process_wait_even_after_both_pipes_close():
    result = run_bounded(
        _python("import os,time;os.close(1);os.close(2);time.sleep(10)"),
        deadline=time.monotonic() + 0.2,
    )
    assert result["status"] == "timeout"
    assert result["returncode"] is not None
    assert not result["stdout_complete"] and not result["stderr_complete"]


def test_expired_deadline_does_not_spawn(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("expired request must not invoke Popen")
    monkeypatch.setattr("tiberium_ai.native_process.subprocess.Popen", forbidden)
    result = run_bounded(["not-called"], deadline=time.monotonic() - 1)
    assert result["status"] == "timeout"
    assert result["started"] is False and result["returncode"] is None
    assert result["stdout"] == result["stderr"] == b""


def test_missing_executable_is_a_start_failure(tmp_path):
    result = run_bounded([str(tmp_path / "missing")], deadline=time.monotonic() + 5)
    assert result["status"] == "failed_to_start"
    assert result["error"] == "FileNotFoundError"
    assert result["started"] is False


def test_missing_working_directory_is_a_start_failure(tmp_path):
    result = run_bounded(_python("pass"), deadline=time.monotonic() + 5, cwd=str(tmp_path / "missing"))
    assert result["status"] == "failed_to_start"
    assert result["started"] is False


def test_metacharacters_are_literal_arguments_without_a_shell(tmp_path):
    marker = tmp_path / "must-not-exist"
    argument = f"; touch {marker}"
    result = run_bounded(_python("import sys;print(sys.argv[1],end='')", argument), deadline=time.monotonic() + 5)
    assert result["stdout"] == argument.encode("utf-8")
    assert not marker.exists()


def test_explicit_working_directory_and_environment_are_used(tmp_path):
    result = run_bounded(
        _python("import os;print(os.getcwd());print(os.environ.get('RUNNER_FIXTURE'))"),
        deadline=time.monotonic() + 5, cwd=str(tmp_path), env=dict(os.environ, RUNNER_FIXTURE="fixture"),
    )
    assert result["status"] == "completed"
    assert result["stdout"].decode("utf-8").splitlines() == [str(tmp_path), "fixture"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_descendant_holding_pipes_does_not_make_parent_exit_a_completion():
    source = "import subprocess,sys\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'])\nprint(p.pid,flush=True)\n"
    started = time.monotonic()
    result = run_bounded(_python(source), deadline=started + 1.0)
    assert result["status"] == "timeout"
    assert result["returncode"] == 0
    assert not result["stdout_complete"]
    assert time.monotonic() - started < 3
    descendant = int(result["stdout"].strip())
    proc = Path(f"/proc/{descendant}/stat")
    if Path("/proc").exists():
        # Some container PID 1 processes retain dead grandchildren as zombies.
        try:
            state = proc.read_text(encoding="utf-8").split(")", 1)[1].split()[0]
        except FileNotFoundError:
            state = None
        assert state in (None, "Z")


def test_keyboard_interrupt_cleans_up_and_propagates(monkeypatch):
    native = subprocess.Popen
    processes = []
    def record(*args, **kwargs):
        process = native(*args, **kwargs)
        processes.append(process)
        return process
    def interrupt(self):
        raise KeyboardInterrupt
    monkeypatch.setattr("tiberium_ai.native_process.subprocess.Popen", record)
    monkeypatch.setattr("tiberium_ai.native_process._Capture.state", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_bounded(_python("import time;time.sleep(10)"), deadline=time.monotonic() + 5)
    assert len(processes) == 1 and processes[0].poll() is not None


def test_reader_start_failure_cleans_unowned_pipes(monkeypatch):
    import tiberium_ai.native_process as native_process
    native_popen = subprocess.Popen
    native_capture = native_process._Capture
    processes = []
    def record(*args, **kwargs):
        process = native_popen(*args, **kwargs)
        processes.append(process)
        return process
    def fail_start():
        raise RuntimeError("fixture reader start failed")
    def capture(*args, **kwargs):
        result = native_capture(*args, **kwargs)
        result.thread.start = fail_start
        return result
    monkeypatch.setattr(native_process.subprocess, "Popen", record)
    monkeypatch.setattr(native_process, "_Capture", capture)
    with pytest.raises(RuntimeError, match="reader start failed"):
        run_bounded(_python("import time;time.sleep(10)"), deadline=time.monotonic() + 5)
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed


@pytest.mark.parametrize("argv", [[], (), [""], ["a\x00b"], ["\ud800"], [1], ["x"] * 33, ["x" * 4097]])
def test_invalid_argv_is_rejected_before_execution(argv):
    with pytest.raises(ValueError):
        run_bounded(argv, deadline=time.monotonic() + 5)


@pytest.mark.parametrize("deadline", [None, True, "5", float("inf"), float("nan"), 10 ** 1000])
def test_invalid_deadline_is_rejected(deadline):
    with pytest.raises(ValueError):
        run_bounded([sys.executable], deadline=deadline)


@pytest.mark.parametrize("name,value", [("max_stdout_bytes", 0), ("max_stderr_bytes", -1), ("max_stdout_bytes", True), ("max_stderr_bytes", 1.5), ("max_stdout_bytes", 1048577)])
def test_invalid_capture_budgets_are_rejected(name, value):
    with pytest.raises(ValueError):
        run_bounded([sys.executable], deadline=time.monotonic() + 5, **{name: value})


@pytest.mark.parametrize("cwd", [False, Path("."), "", "x\x00y", "\ud800"])
def test_invalid_cwd_is_rejected(cwd):
    with pytest.raises(ValueError):
        run_bounded([sys.executable], deadline=time.monotonic() + 5, cwd=cwd)


@pytest.mark.parametrize("env", [[], {1: "x"}, {"x": 1}, {"": "x"}, {"a=b": "x"}, {"x": "a\x00b"}, {"x": "\ud800"}, {"x": "v" * 65537}, {str(i): "v" for i in range(513)}])
def test_invalid_environment_is_rejected(env):
    with pytest.raises(ValueError):
        run_bounded([sys.executable], deadline=time.monotonic() + 5, env=env)
