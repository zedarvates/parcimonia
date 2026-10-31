"""Protocol tests use fake native responses, not claimed OCR quality results."""

import binascii
from copy import deepcopy
import hashlib
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

import tiberium_ai.asset_text_extract as module
from tiberium_ai.asset_text_extract import extract_asset_text


HEADER = b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
TSV = HEADER + b"5\t1\t1\t1\t1\t1\t10\t10\t60\t20\t95.0\tROBOT\n"
PDF = b"%PDF-1.4\nfixture source bytes; native runner is replaced in protocol tests\n"


def _png(width=300, height=100):
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr + struct.pack(">I", binascii.crc32(ihdr) & 0xFFFFFFFF)


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
    values = {"data": _png(), "filename": "image.png", "source_id": "fixture", "revision": "v1", "backend": "tesseract", "executable": str(tool)}
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


def test_ocr_protocol_binds_source_tool_text_and_observed_boxes(monkeypatch, tool):
    calls = _fake(monkeypatch, [_result(b"tesseract 5.5.0\n"), _result(TSV)])
    source = _png()
    report = extract_asset_text(**_request(tool, data=source, filename="untrusted;source.png"))
    assert report["status"] == "completed"
    assert report["text"] == "ROBOT"
    assert report["source"]["filename"] == "untrusted;source.png"
    assert report["sample_sha256"] == hashlib.sha256(source).hexdigest()
    assert report["backend"]["executable_sha256"] == hashlib.sha256(tool.read_bytes()).hexdigest()
    assert report["backend"]["version"] == "tesseract 5.5.0"
    assert report["backend"]["weights_hash"] is None
    assert report["limits"]["ocr_scores"] == "uncalibrated"
    assert report["limits"]["native_inference"] == "local_ocr"
    assert report["evidence"][0]["bbox"] == [10, 10, 60, 20]
    assert calls[0][0] == [str(tool.resolve()), "--version"]
    assert calls[1][0][2:] == ["stdout", "-l", "eng", "--oem", "1", "--psm", "6", "tsv"]
    assert calls[0][1]["deadline"] == calls[1][1]["deadline"]
    assert calls[0][1]["env"]["OMP_THREAD_LIMIT"] == "1"
    assert calls[0][1]["env"]["LC_ALL"] == "C"
    assert "untrusted;source.png" not in calls[1][0]
    assert not Path(calls[1][1]["cwd"]).exists()
    assert set(report) == {"schema", "source", "input_hash", "sample_sha256", "source_complete", "backend", "status", "text", "evidence", "coverage", "reason_codes", "native_calls", "elapsed_ms", "limits"}
    assert "stdout" not in report["native_calls"][1]
    assert "env" not in report


def test_snapshot_contains_exact_source_and_is_removed_on_failure(monkeypatch, tool):
    source = _png()
    seen = []
    def failure(argv, kwargs):
        snapshot = Path(argv[1])
        assert snapshot.name == "input.png"
        assert snapshot.read_bytes() == source
        seen.append(snapshot)
        return _result(b"partial data", b"native error", returncode=1)
    _fake(monkeypatch, [_result(b"tesseract 5.5.0\n"), failure])
    report = extract_asset_text(**_request(tool, data=source))
    assert report["status"] == "failed"
    assert report["text"] is None and report["evidence"] == []
    assert not seen[0].exists()


def test_pdf_uses_bounded_page_range_and_preserves_page_evidence(monkeypatch, tool):
    calls = _fake(monkeypatch, [_result(stderr=b"pdftotext version 25.03.0\nCopyright fixture\n"), _result(b"ROBOT garden.\n\f")])
    report = extract_asset_text(**_request(tool, data=PDF, filename="document.pdf", backend="pdftotext", max_pages=2))
    assert report["status"] == "completed"
    assert report["text"] == "ROBOT garden.\n\f"
    assert report["backend"]["language"] is None
    assert report["coverage"]["pages_requested"] == [1, 2]
    assert report["coverage"]["document_complete"] == "not_established"
    assert calls[0][0] == [str(tool.resolve()), "-v"]
    assert calls[1][0][1:9] == ["-f", "1", "-l", "2", "-enc", "UTF-8", "-eol", "unix"]
    assert calls[1][0][-1] == "-"
    assert len(report["native_calls"]) == 2


def test_empty_pdf_success_is_not_a_failure_or_absence_assertion(monkeypatch, tool):
    _fake(monkeypatch, [_result(stderr=b"pdftotext version 25.03.0\n"), _result()])
    report = extract_asset_text(**_request(tool, backend="pdftotext", data=PDF))
    assert report["status"] == "completed"
    assert report["text"] == ""
    assert "no_text_extracted" in report["reason_codes"]
    assert report["coverage"]["document_complete"] == "not_established"


@pytest.mark.parametrize("changes,reason", [
    ({"complete": False}, "complete_source_required"),
    ({"data": b"not an image"}, "unsupported_image_format"),
    ({"data": _png()[:-1]}, "image_header_unusable"),
    ({"data": _png(3000, 2000)}, "image_pixel_budget_exceeded"),
    ({"backend": "pdftotext", "data": b"not a PDF"}, "unsupported_pdf_signature"),
])
def test_unsupported_input_never_starts_a_process(monkeypatch, tool, changes, reason):
    calls = _fake(monkeypatch, [])
    report = extract_asset_text(**_request(tool, **changes))
    assert report["status"] == "indeterminate"
    assert report["reason_codes"] == [reason]
    assert calls == []
    assert report["native_calls"] == []


@pytest.mark.parametrize("changes", [
    {"data": "image"}, {"data": bytearray(b"image")}, {"data": b"a" * (1024 * 1024 + 1)},
    {"filename": ""}, {"filename": " image.png"}, {"filename": "a\x00.png"},
    {"source_id": "\ud800"}, {"revision": "r" * 1025}, {"backend": "ocr"}, {"backend": []},
    {"complete": 1}, {"max_pages": True}, {"max_pages": 0}, {"max_pages": 9},
    {"timeout_s": True}, {"timeout_s": 0}, {"timeout_s": 31}, {"timeout_s": float("nan")},
    {"timeout_s": float("inf")}, {"timeout_s": 10 ** 5000},
    {"language": "eng+fra"}, {"language": "../eng"}, {"language": "osd"}, {"language": None},
    {"executable": ""}, {"executable": Path("tool")},
])
def test_bad_arguments_raise_without_native_execution(monkeypatch, tool, changes):
    calls = _fake(monkeypatch, [])
    with pytest.raises(ValueError):
        extract_asset_text(**_request(tool, **changes))
    assert calls == []


def test_discovery_absent_is_unavailable_without_native_calls(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda backend: None)
    report = extract_asset_text(_png(), filename="image.png", source_id="fixture", revision="v1", backend="tesseract")
    assert report["status"] == "unavailable"
    assert report["reason_codes"] == ["executable_not_found"]
    assert report["native_calls"] == []


@pytest.mark.parametrize("target", ["missing", "directory"])
def test_explicit_unusable_executable_is_unavailable(monkeypatch, tmp_path, target):
    path = tmp_path / target
    if target == "directory":
        path.mkdir()
    calls = _fake(monkeypatch, [])
    report = extract_asset_text(**_request(path))
    assert report["status"] == "unavailable"
    assert calls == []


@pytest.mark.parametrize("response,status,reason", [
    (_result(returncode=1, stderr=b"cannot load language"), "failed", "native_exit_nonzero"),
    (_result(status="timeout", returncode=None, stdout_complete=False, stderr_complete=False), "indeterminate", "native_timeout"),
    (_result(status="output_limit", returncode=None, stdout_complete=False, stderr_complete=False), "indeterminate", "native_output_limit"),
    (_result(status="failed_to_start", returncode=None, stdout_complete=False, stderr_complete=False, started=False, error="FileNotFoundError"), "unavailable", "native_start_failed"),
    (_result(error="pipe_read_error:OSError", stdout_complete=False), "failed", "native_response_incomplete"),
])
def test_native_failures_are_not_empty_text_success(monkeypatch, tool, response, status, reason):
    calls = _fake(monkeypatch, [_result(b"tesseract 5.5.0\n"), response])
    report = extract_asset_text(**_request(tool))
    assert report["status"] == status
    assert report["reason_codes"] == [reason]
    assert report["text"] is None and report["evidence"] == [] and report["coverage"] is None
    assert len(calls) == 2


@pytest.mark.parametrize("version", [b"", b"not tesseract\n", b"tesseract 3.05\n", b"\xff"])
def test_unrecognized_version_prevents_extraction(monkeypatch, tool, version):
    calls = _fake(monkeypatch, [_result(version)])
    report = extract_asset_text(**_request(tool))
    assert report["status"] == "failed"
    assert report["reason_codes"] == ["backend_version_unusable"]
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [b"not TSV", b"\xff", HEADER + b"bad row\n"])
def test_invalid_native_text_is_not_used(monkeypatch, tool, payload):
    _fake(monkeypatch, [_result(b"tesseract 5.5.0\n"), _result(payload)])
    report = extract_asset_text(**_request(tool))
    assert report["status"] == "failed"
    assert report["reason_codes"] == ["native_text_response_invalid"]
    assert report["text"] is None


def test_identity_change_invalidates_otherwise_valid_output(monkeypatch, tool):
    def changed(argv, kwargs):
        tool.write_bytes(b"different executable identity")
        return _result(TSV)
    _fake(monkeypatch, [_result(b"tesseract 5.5.0\n"), changed])
    report = extract_asset_text(**_request(tool))
    assert report["status"] == "failed"
    assert report["reason_codes"] == ["executable_identity_changed"]
    assert report["text"] is None


def test_one_absolute_deadline_survives_preflight_and_parsing(monkeypatch, tool):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    def version(argv, kwargs):
        clock.now += 3
        return _result(b"tesseract 5.5.0\n")
    def extraction(argv, kwargs):
        clock.now += 2
        return _result(TSV)
    calls = _fake(monkeypatch, [version, extraction])
    report = extract_asset_text(**_request(tool, timeout_s=6))
    assert report["status"] == "completed"
    assert {kwargs["deadline"] for _, kwargs in calls} == {106.0}
    assert report["elapsed_ms"] == 5000.0


def test_exhausted_preflight_budget_starts_no_extraction(monkeypatch, tool):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    def version(argv, kwargs):
        clock.now += 6
        return _result(b"tesseract 5.5.0\n")
    calls = _fake(monkeypatch, [version])
    report = extract_asset_text(**_request(tool, timeout_s=5))
    assert report["status"] == "indeterminate"
    assert report["reason_codes"] == ["deadline_exceeded"]
    assert len(calls) == 1


def test_parser_crossing_the_deadline_cannot_publish_completed_text(monkeypatch, tool):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    _fake(monkeypatch, [_result(b"tesseract 5.5.0\n"), _result(TSV)])
    native_parser = module.parse_tesseract_tsv
    def slow_parser(*args, **kwargs):
        parsed = native_parser(*args, **kwargs)
        clock.now = 107.0
        return parsed
    monkeypatch.setattr(module, "parse_tesseract_tsv", slow_parser)
    report = extract_asset_text(**_request(tool, timeout_s=6))
    assert report["status"] == "indeterminate"
    assert report["reason_codes"] == ["deadline_exceeded"]
    assert report["text"] is None and report["evidence"] == [] and report["coverage"] is None


def test_source_options_and_revision_are_bound_to_input_hash(monkeypatch, tool):
    calls = _fake(monkeypatch, [_result(b"tesseract 5.5.0\n"), _result(TSV)] * 6)
    baseline = extract_asset_text(**_request(tool))
    for changes in [{"revision": "v2"}, {"language": "fra"}, {"max_pages": 2}, {"timeout_s": 9}, {"data": _png(301, 100)}]:
        result = extract_asset_text(**_request(tool, **changes))
        assert result["input_hash"] != baseline["input_hash"]
    assert len(calls) == 12


def test_keyboard_interrupt_propagates_after_snapshot_cleanup(monkeypatch, tool):
    directories = []
    def interrupted(argv, kwargs):
        directories.append(Path(kwargs["cwd"]))
        raise KeyboardInterrupt
    _fake(monkeypatch, [interrupted])
    with pytest.raises(KeyboardInterrupt):
        extract_asset_text(**_request(tool))
    assert not directories[0].exists()
