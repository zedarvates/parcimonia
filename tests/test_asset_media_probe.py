"""Protocol checks use fake native responses, not media-quality assertions."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

import tiberium_ai.asset_media_probe as module
from tiberium_ai.asset_media_probe import probe_asset_media
from tiberium_ai.verification import hash_input


VERSION = b"ffprobe version 7.1.1 Copyright fixture\nconfiguration: unused\n"


def _wav():
    fmt = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", 8) + b"\x00" * 8
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks


def _bmff(major=b"isom", compatible=(), *, extended=False):
    payload = major + b"\x00" * 4 + b"".join(compatible)
    if extended:
        return struct.pack(">I4sQ", 1, b"ftyp", len(payload) + 16) + payload
    return struct.pack(">I4s", len(payload) + 8, b"ftyp") + payload


def _payload(demuxer="wav"):
    stream = {"index": 0, "codec_name": "pcm_s16le", "codec_type": "audio", "sample_rate": "8000", "channels": 1, "duration": "0.000500", "disposition": {"attached_pic": 0}}
    return json.dumps({"programs": [], "stream_groups": [], "streams": [stream], "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2" if demuxer == "mov" else demuxer, "duration": "0.000500"}}, separators=(",", ":")).encode()


def _result(stdout=b"", stderr=b"", **changes):
    result = {"status": "completed", "returncode": 0, "stdout": stdout, "stderr": stderr, "stdout_complete": True, "stderr_complete": True, "started": True, "error": None, "elapsed_ms": 0.25}
    result.update(changes)
    return result


@pytest.fixture
def tool(tmp_path):
    path = tmp_path / "selected-tool"
    path.write_bytes(b"fixture native executable identity")
    path.chmod(0o700)
    return path


def _request(tool, **changes):
    values = {"data": _wav(), "filename": "untrusted;name.mp4", "source_id": "fixture", "revision": "v1", "executable": str(tool)}
    values.update(changes)
    return values


def _fake(monkeypatch, responses):
    calls = []
    pending = list(responses)
    def invoke(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        assert pending, "No implicit retry or fallback is allowed"
        response = pending.pop(0)
        return response(argv, kwargs) if callable(response) else deepcopy(response)
    monkeypatch.setattr(module, "run_bounded", invoke)
    return calls


def test_protocol_binds_exact_source_raw_json_tool_and_forced_profile(monkeypatch, tool):
    raw = _payload()
    source = _wav()
    def probe(argv, kwargs):
        snapshot = Path(argv[-1])
        assert snapshot.name == "input.bin" and snapshot.read_bytes() == source
        assert snapshot.parent == Path(kwargs["cwd"])
        return _result(raw)
    calls = _fake(monkeypatch, [_result(VERSION), probe])
    report = probe_asset_media(**_request(tool, data=source))
    assert report["status"] == "completed"
    assert report["source"] == {"id": "fixture", "revision": "v1", "filename": "untrusted;name.mp4"}
    assert report["profile"] == {"id": module.PROFILE_ID, "source_format": "wav", "demuxer": "wav"}
    assert report["sample_sha256"] == hashlib.sha256(source).hexdigest()
    assert report["source_complete"] is True
    assert report["raw_json"].encode("utf-8") == raw
    assert report["projection"]["streams"][0]["sample_rate"] == 8000
    assert report["projection"]["coverage"]["full_decode"] == "not_established"
    assert report["backend"] == {"id": "ffprobe", "version": VERSION.decode().splitlines()[0], "executable": str(tool.resolve()), "executable_sha256": hashlib.sha256(tool.read_bytes()).hexdigest()}
    assert report["input_hash"] == hash_input({"source": report["source"], "sample_sha256": report["sample_sha256"], "complete": True, "backend": "ffprobe", "executable_requested": str(tool), "timeout_s": 10.0, "profile": report["profile"]})
    assert calls[0][0] == [str(tool.resolve()), "-version"]
    assert calls[1][0][1:13] == ["-v", "error", "-protocol_whitelist", "file", "-f", "wav", "-probesize", "1048576", "-analyzeduration", "1000000", "-max_probe_packets", "128"]
    assert calls[1][0][13:-1] == ["-show_entries", "stream=index,codec_name,codec_type,width,height,sample_rate,channels,duration:stream_disposition=attached_pic:format=format_name,duration", "-of", "json=string_validation=fail", "-i"]
    assert len(calls[1][0]) <= 32 and "untrusted;name.mp4" not in calls[1][0]
    assert calls[0][1]["deadline"] == calls[1][1]["deadline"]
    assert calls[0][1]["max_stdout_bytes"] == calls[0][1]["max_stderr_bytes"] == 8192
    assert calls[1][1]["max_stdout_bytes"] == 65536 and calls[1][1]["max_stderr_bytes"] == 32768
    assert calls[1][1]["env"]["OMP_THREAD_LIMIT"] == "1" and calls[1][1]["env"]["LC_ALL"] == "C"
    assert not Path(calls[1][1]["cwd"]).exists()
    assert [call["phase"] for call in report["native_calls"]] == ["version", "probe"]
    assert report["native_calls"][1]["stdout_sha256"] == hashlib.sha256(raw).hexdigest()
    assert set(report) == {"schema", "source", "input_hash", "sample_sha256", "source_complete", "backend", "profile", "status", "raw_json", "projection", "reason_codes", "native_calls", "elapsed_ms", "limits"}
    assert "stdout" not in report["native_calls"][1] and "env" not in report
    assert report["limits"]["native_media"] == "reported_streams_not_full_decode"
    assert report["limits"]["protocols"] == "file_only_not_os_sandbox"
    assert report["limits"]["model_calls"] == 0


@pytest.mark.parametrize("data,demuxer", [(b"fLaC", "flac"), (b"OggS", "ogg"), (_bmff(), "mov"), (_bmff(b"qt  ", (b"isom",), extended=True), "mov")])
def test_only_signature_selected_demuxer_is_used(monkeypatch, tool, data, demuxer):
    calls = _fake(monkeypatch, [_result(VERSION), _result(_payload(demuxer))])
    report = probe_asset_media(**_request(tool, data=data, filename="https://example.invalid/not-input.wav"))
    assert report["status"] == "completed"
    assert report["profile"]["demuxer"] == demuxer
    args = calls[1][0]
    assert args[args.index("-f") + 1] == demuxer
    if demuxer == "mov":
        assert args[13:17] == ["-enable_drefs", "0", "-use_absolute_path", "0"]
    else:
        assert "-enable_drefs" not in args and "-use_absolute_path" not in args


@pytest.mark.parametrize("data,reason", [
    (b"", "unsupported_media_format"), (b"#EXTM3U\nhttps://example.invalid/stream", "unsupported_media_format"),
    (_wav()[:-1], "media_header_unusable"), (_bmff()[:-1], "media_header_unusable"),
    (_bmff(b"avif"), "unsupported_bmff_brand"), (_bmff(b"heic"), "unsupported_bmff_brand"),
    (_bmff(b"isom", (b"avif",)), "unsupported_bmff_brand"),
    (_bmff(b"isom", (b"heic",), extended=True), "unsupported_bmff_brand"),
    (_bmff(b"isom", (b"\xffabc",)), "unsupported_bmff_brand"),
])
def test_unsupported_or_unusable_input_never_starts_a_process(monkeypatch, tool, data, reason):
    calls = _fake(monkeypatch, [])
    report = probe_asset_media(**_request(tool, data=data))
    assert report["status"] == "indeterminate" and report["reason_codes"] == [reason]
    assert calls == [] and report["native_calls"] == []
    assert report["raw_json"] is None and report["projection"] is None


def test_prefix_does_not_even_parse_headers(monkeypatch, tool):
    calls = _fake(monkeypatch, [])
    monkeypatch.setattr(module, "probe_media", lambda *args, **kwargs: pytest.fail("No complete-source header parse for a prefix"))
    report = probe_asset_media(**_request(tool, complete=False))
    assert report["reason_codes"] == ["complete_source_required"] and report["source_complete"] is False
    assert calls == []


@pytest.mark.parametrize("changes", [
    {"data": "wav"}, {"data": bytearray(b"wav")}, {"data": b"x" * (1024 * 1024 + 1)},
    {"filename": ""}, {"filename": " file.wav"}, {"filename": "x\x00.wav"},
    {"source_id": "\ud800"}, {"revision": "r" * 1025}, {"complete": 1},
    {"timeout_s": True}, {"timeout_s": 0}, {"timeout_s": -1}, {"timeout_s": 31},
    {"timeout_s": float("nan")}, {"timeout_s": float("inf")}, {"timeout_s": 10 ** 5000},
    {"executable": ""}, {"executable": Path("tool")},
])
def test_invalid_arguments_raise_without_native_execution(monkeypatch, tool, changes):
    calls = _fake(monkeypatch, [])
    with pytest.raises(ValueError):
        probe_asset_media(**_request(tool, **changes))
    assert calls == []


def test_missing_discovery_is_unavailable(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    report = probe_asset_media(_wav(), filename="a.wav", source_id="a", revision="v1")
    assert report["status"] == "unavailable" and report["reason_codes"] == ["executable_not_found"]
    assert report["native_calls"] == []


@pytest.mark.parametrize("target", ["missing", "directory"])
def test_explicit_unusable_tool_is_unavailable(monkeypatch, tmp_path, target):
    path = tmp_path / target
    if target == "directory":
        path.mkdir()
    calls = _fake(monkeypatch, [])
    assert probe_asset_media(**_request(path))["status"] == "unavailable"
    assert calls == []


@pytest.mark.parametrize("phase", ["version", "probe"])
@pytest.mark.parametrize("response,status,reason", [
    (_result(returncode=1), "failed", "native_exit_nonzero"),
    (_result(status="timeout", returncode=None, stdout_complete=False), "indeterminate", "native_timeout"),
    (_result(status="output_limit", returncode=None, stdout_complete=False), "indeterminate", "native_output_limit"),
    (_result(status="failed_to_start", returncode=None, started=False, error="FileNotFoundError"), "unavailable", "native_start_failed"),
    (_result(error="pipe_read_error:OSError", stdout_complete=False), "failed", "native_response_incomplete"),
    (_result(started=False), "failed", "native_response_incomplete"),
])
def test_incomplete_or_failed_transport_is_never_a_media_success(monkeypatch, tool, phase, response, status, reason):
    responses = [response] if phase == "version" else [_result(VERSION), response]
    calls = _fake(monkeypatch, responses)
    report = probe_asset_media(**_request(tool))
    assert report["status"] == status and report["reason_codes"] == [reason]
    assert report["raw_json"] is None and report["projection"] is None
    assert len(calls) == len(responses)
    assert not Path(calls[-1][1]["cwd"]).exists()


@pytest.mark.parametrize("version", [b"", b"ffprobe version 3.4.9\n", b"ffprobe version n3.4.9\n", b"not ffprobe\n", b"\nffprobe version 7.1\n", b"ffprobe version N-12345-gabc\n", b"\xff", b"ffprobe version 7.1 \x00\n"])
def test_unknown_version_stops_before_media_probe(monkeypatch, tool, version):
    calls = _fake(monkeypatch, [_result(version)])
    report = probe_asset_media(**_request(tool))
    assert report["status"] == "failed" and report["reason_codes"] == ["backend_version_unusable"]
    assert len(calls) == 1


@pytest.mark.parametrize("version", [
    b"ffprobe version n9.0.2-39-g7adfbe40dc-20261031\n",
    b"ffprobe version n8.1.0\n",
])
def test_numbered_release_tag_versions_keep_observed_identity(monkeypatch, tool, version):
    calls = _fake(monkeypatch, [_result(version), _result(_payload())])
    report = probe_asset_media(**_request(tool))
    assert report["status"] == "completed"
    assert report["backend"]["version"] == version.decode().strip()
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [b"", b"not JSON", b"\xff", b'{"format":{"format_name":"ogg"},"streams":[]}', b'{"format":{"format_name":"wav"},"streams":[],"extra":1}'])
def test_invalid_native_json_is_not_retained(monkeypatch, tool, payload):
    _fake(monkeypatch, [_result(VERSION), _result(payload)])
    report = probe_asset_media(**_request(tool))
    assert report["status"] == "failed" and report["reason_codes"] == ["native_media_response_invalid"]
    assert report["raw_json"] is None and report["projection"] is None


def test_detectable_executable_change_discards_native_output(monkeypatch, tool):
    def changed(argv, kwargs):
        tool.write_bytes(b"changed native executable identity")
        return _result(_payload())
    _fake(monkeypatch, [_result(VERSION), changed])
    report = probe_asset_media(**_request(tool))
    assert report["status"] == "failed" and report["reason_codes"] == ["executable_identity_changed"]
    assert report["raw_json"] is None and report["projection"] is None


def test_identity_size_failure_prevents_native_execution(monkeypatch, tool):
    def unavailable(path, deadline):
        raise module._IdentityError("executable_identity_unavailable")
    monkeypatch.setattr(module, "_identity", unavailable)
    calls = _fake(monkeypatch, [])
    report = probe_asset_media(**_request(tool))
    assert report["status"] == "indeterminate" and report["reason_codes"] == ["executable_identity_unavailable"]
    assert calls == []


@pytest.mark.parametrize("late_phase", ["version", "parser", "cleanup", "failed_cleanup"])
def test_global_deadline_includes_preflight_parser_and_cleanup(monkeypatch, tool, late_phase):
    clock = [module.time.monotonic()]
    start = clock[0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    identities = []
    def identity(path, deadline):
        identities.append(deadline)
        return "a" * 64
    monkeypatch.setattr(module, "_identity", identity)
    def version(argv, kwargs):
        clock[0] = start + (2.1 if late_phase == "version" else 0.4)
        return _result(VERSION)
    calls = _fake(monkeypatch, [version, _result(_payload(), returncode=1 if late_phase == "failed_cleanup" else 0)])
    parser = module.parse_ffprobe_json
    def delayed_parser(payload, **kwargs):
        result = parser(payload, **kwargs)
        if late_phase == "parser":
            clock[0] = start + 2.1
        return result
    monkeypatch.setattr(module, "parse_ffprobe_json", delayed_parser)
    if late_phase in {"cleanup", "failed_cleanup"}:
        original = module.tempfile.TemporaryDirectory
        class DelayedCleanup:
            def __init__(self, **kwargs):
                self.temporary = original(**kwargs)
            def __enter__(self):
                return self.temporary.__enter__()
            def __exit__(self, *args):
                result = self.temporary.__exit__(*args)
                clock[0] = start + 2.1
                return result
        monkeypatch.setattr(module.tempfile, "TemporaryDirectory", DelayedCleanup)
    report = probe_asset_media(**_request(tool, timeout_s=2))
    if late_phase == "failed_cleanup":
        assert report["status"] == "failed" and report["reason_codes"] == ["native_exit_nonzero"]
    else:
        assert report["status"] == "indeterminate" and report["reason_codes"] == ["deadline_exceeded"]
    assert report["raw_json"] is None and report["projection"] is None
    assert report["elapsed_ms"] >= 2100 - 0.001
    assert all(deadline == start + 2 for deadline in identities)
    assert all(kwargs["deadline"] == start + 2 for _, kwargs in calls)
    assert len(calls) == (1 if late_phase == "version" else 2)
    assert not Path(calls[-1][1]["cwd"]).exists()


def test_request_hash_changes_with_revision_options_bytes_and_source_completeness(monkeypatch, tool):
    def request(**changes):
        _fake(monkeypatch, [_result(VERSION), _result(_payload())])
        return probe_asset_media(**_request(tool, **changes))["input_hash"]
    hashes = {request(), request(revision="v2"), request(timeout_s=9), request(data=_wav() + b"x"), request(complete=False)}
    assert len(hashes) == 5


def test_interrupt_still_removes_the_owned_snapshot(monkeypatch, tool):
    seen = []
    def interrupted(argv, kwargs):
        seen.append(Path(argv[-1]))
        assert seen[0].is_file()
        raise KeyboardInterrupt
    _fake(monkeypatch, [_result(VERSION), interrupted])
    with pytest.raises(KeyboardInterrupt):
        probe_asset_media(**_request(tool))
    assert not seen[0].exists() and not seen[0].parent.exists()
