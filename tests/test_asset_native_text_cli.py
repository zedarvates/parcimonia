"""CLI protocol and review persistence, without invoking a native executable.

PDF source bytes are an authored signature fixture. Extracted text and native
call records are synthetic declarations parsed into coherent page evidence;
these tests do not measure OCR accuracy or attest an installed tool.
"""

from copy import deepcopy
import hashlib
import json

import pytest

import tiberium_ai.asset_cli as cli
from tiberium_ai.asset_inspection import MAX_SAMPLE_BYTES, inspect_asset
from tiberium_ai.text_evidence import parse_pdf_text
from tiberium_ai.verification import hash_input


PDF_SOURCE = b"%PDF-1.4\nCLI protocol fixture; no native extraction is performed\n"
TOPICS = {"robotique": ["robot"], "jardinage": ["jardin"]}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _extraction(inspection, payload=b"Un ROBOT.\n\fUn jardin.\n\f"):
    parsed = parse_pdf_text(payload, max_pages=3)
    version = b"pdftotext version fixture-only\n"
    def call(phase, output):
        return {
            "phase": phase, "status": "completed", "returncode": 0,
            "stdout_sha256": _sha(output), "stderr_sha256": _sha(b""),
            "stdout_complete": True, "stderr_complete": True,
            "started": True, "error": None, "elapsed_ms": 0.25,
        }
    return {
        "schema": "parcimonia.asset-text-extraction/v1",
        "source": deepcopy(inspection["source"]),
        "input_hash": hash_input({"fixture": "authored", "payload_sha256": _sha(payload)}),
        "sample_sha256": inspection["sample"]["sha256"], "source_complete": True,
        "backend": {
            "id": "pdftotext", "version": version.decode().strip(),
            "executable": "/declared-fixture-only/pdftotext",
            "executable_sha256": _sha(b"declared identity, not executable bytes"),
            "language": None, "weights_hash": None,
        },
        "status": "completed", "text": parsed["text"],
        "evidence": parsed["evidence"], "coverage": parsed["coverage"],
        "reason_codes": ["authored_protocol_fixture"],
        "native_calls": [call("version", version), call("extract", payload)],
        "elapsed_ms": 0.5, "limits": {"fixture": "not_native_quality_evidence"},
    }


def _setup(tmp_path):
    source = tmp_path / "fixture.pdf"
    source.write_bytes(PDF_SOURCE)
    inspection = inspect_asset(PDF_SOURCE, filename=source.name, source_id="fixture:cli", revision="v1")
    report = _write_json(tmp_path / "inspection.json", inspection)
    extraction = _write_json(tmp_path / "extraction.json", _extraction(inspection))
    topics = _write_json(tmp_path / "topics.json", TOPICS)
    return source, report, extraction, topics


def _extract_args(path, *extra):
    return ["extract-text", str(path), "--source-id", "fixture:cli", "--revision", "v1", "--backend", "pdftotext", *extra]


def _enrich_args(report, extraction, topics=None):
    return ["enrich-text", str(report), str(extraction), *(["--topics", str(topics)] if topics else [])]


def _success(capsys, arguments):
    assert cli.main(arguments) == 0
    output = capsys.readouterr()
    assert output.err == ""
    return json.loads(output.out)


def _forbid_native(*args, **kwargs):
    pytest.fail("This CLI protocol test must not invoke a native executable.")


@pytest.mark.parametrize("status,code", [("completed", 0), ("indeterminate", 3), ("unavailable", 3), ("failed", 4)])
def test_extract_command_serializes_status_and_forwards_explicit_options(tmp_path, capsys, monkeypatch, status, code):
    source, report_path, _, _ = _setup(tmp_path)
    inspection = json.loads(report_path.read_text(encoding="utf-8"))
    response = _extraction(inspection)
    response["status"] = status
    if status != "completed":
        response.update(text=None, evidence=[], coverage=None, reason_codes=["fixture_failure"])
    calls = []
    def extract(data, **options):
        calls.append((data, options))
        return response
    monkeypatch.setattr(cli, "extract_asset_text", extract)
    before = source.read_bytes()
    assert cli.main(_extract_args(source, "--executable", "/explicit/tool", "--language", "fra", "--max-pages", "2", "--timeout", "1.5")) == code
    output = capsys.readouterr()
    assert output.err == "" and json.loads(output.out) == response
    assert calls == [(before, {
        "filename": "fixture.pdf", "source_id": "fixture:cli", "revision": "v1",
        "backend": "pdftotext", "executable": "/explicit/tool", "language": "fra",
        "max_pages": 2, "timeout_s": 1.5, "complete": True,
    })]
    assert source.read_bytes() == before


@pytest.mark.parametrize("extra,complete,reason", [(0, True, "executable_unavailable"), (37, False, "complete_source_required")])
def test_extract_read_budget_keeps_a_prefix_distinct_from_a_complete_source(tmp_path, capsys, monkeypatch, extra, complete, reason):
    monkeypatch.setattr("tiberium_ai.asset_text_extract.run_bounded", _forbid_native)
    source = tmp_path / "large.pdf"
    payload = PDF_SOURCE + b" " * (MAX_SAMPLE_BYTES + extra - len(PDF_SOURCE))
    source.write_bytes(payload)
    assert cli.main(_extract_args(source, "--executable", str(tmp_path / "absent-tool"))) == 3
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert output.err == ""
    assert report["source_complete"] is complete
    assert report["sample_sha256"] == _sha(payload[:MAX_SAMPLE_BYTES])
    assert report["reason_codes"] == [reason]
    assert report["native_calls"] == [] and report["text"] is None
    assert source.read_bytes() == payload


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_extract_rejects_non_regular_sources_before_backend_selection(tmp_path, capsys, monkeypatch, kind):
    monkeypatch.setattr(cli, "extract_asset_text", _forbid_native)
    source = tmp_path / "source.pdf"
    if kind == "directory":
        source.mkdir()
    elif kind == "symlink":
        target = tmp_path / "target.pdf"
        target.write_bytes(PDF_SOURCE)
        try:
            source.symlink_to(target)
        except OSError:
            pytest.skip("Host cannot create symlinks")
    assert cli.main(_extract_args(source)) == 2
    output = capsys.readouterr()
    assert output.out == "" and "error" in json.loads(output.err)


def test_unsupported_source_is_an_indeterminate_report_without_native_calls(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("tiberium_ai.asset_text_extract.run_bounded", _forbid_native)
    source = tmp_path / "notes.txt"
    source.write_text("A robot.", encoding="utf-8")
    assert cli.main(_extract_args(source)) == 3
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert output.err == "" and report["status"] == "indeterminate"
    assert report["reason_codes"] == ["unsupported_pdf_signature"]
    assert report["native_calls"] == [] and report["text"] is None


@pytest.mark.parametrize("option,value", [("--timeout", "0"), ("--timeout", "nan"), ("--max-pages", "9"), ("--language", "../eng")])
def test_invalid_extraction_options_are_input_errors_not_empty_text(tmp_path, capsys, monkeypatch, option, value):
    monkeypatch.setattr("tiberium_ai.asset_text_extract.run_bounded", _forbid_native)
    source = tmp_path / "fixture.pdf"
    source.write_bytes(PDF_SOURCE)
    assert cli.main(_extract_args(source, option, value)) == 2
    output = capsys.readouterr()
    assert output.out == "" and json.loads(output.err)["error"] == "ValueError"


def test_enrich_uses_existing_record_and_preserves_input_files(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "extract_asset_text", _forbid_native)
    monkeypatch.setattr("tiberium_ai.asset_text_extract.run_bounded", _forbid_native)
    paths = _setup(tmp_path)
    source, inspection_path, extraction_path, topics_path = paths
    originals = {path: path.read_bytes() for path in paths}
    report = _success(capsys, _enrich_args(inspection_path, extraction_path, topics_path))
    assert report["analyser"] == {"id": "asset-text-enrichment", "version": "1"}
    assert report["format"]["detected"] == "pdf"
    assert {tag["value"] for tag in report["tag_proposals"] if tag["namespace"] == "topic"} == set(TOPICS)
    assert all(tag["status"] == "proposed" for tag in report["tag_proposals"])
    pages = [item for item in report["evidence"] if item["kind"] == "pdf_page_text"]
    assert {item["page"] for item in pages} == {1, 2}
    assert {path: path.read_bytes() for path in originals} == originals
    assert set(tmp_path.iterdir()) == set(paths)
    assert source.read_bytes() == PDF_SOURCE


@pytest.mark.parametrize("change", ["id", "revision", "filename", "digest", "incomplete", "failed"])
def test_enrich_rejects_a_different_or_unusable_extraction(tmp_path, capsys, monkeypatch, change):
    monkeypatch.setattr(cli, "extract_asset_text", _forbid_native)
    _, report_path, extraction_path, topics_path = _setup(tmp_path)
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    if change in {"id", "revision", "filename"}:
        extraction["source"][change] += ":changed"
    elif change == "digest":
        extraction["sample_sha256"] = "f" * 64
    elif change == "incomplete":
        extraction["source_complete"] = False
    else:
        extraction.update(status="failed", text=None, evidence=[], coverage=None)
    _write_json(extraction_path, extraction)
    assert cli.main(_enrich_args(report_path, extraction_path, topics_path)) == 2
    output = capsys.readouterr()
    assert output.out == "" and json.loads(output.err)["error"] == "ValueError"


def test_enriched_report_round_trips_through_catalogue_review_and_exact_replay(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "extract_asset_text", _forbid_native)
    monkeypatch.setattr("tiberium_ai.asset_text_extract.run_bounded", _forbid_native)
    source, inspection_path, extraction_path, topics_path = _setup(tmp_path)
    enriched = _success(capsys, _enrich_args(inspection_path, extraction_path, topics_path))
    report_path = _write_json(tmp_path / "enriched.json", enriched)
    catalogue = _write_json(tmp_path / "catalogue.json", [enriched])
    initial, accepted = tmp_path / "journal0.json", tmp_path / "journal1.json"
    originals = {path: path.read_bytes() for path in (source, inspection_path, extraction_path, topics_path, report_path)}
    assert _success(capsys, ["search", str(catalogue), "--tag", "topic:robotique"])["count"] == 1
    assert _success(capsys, ["review-init", str(initial)])["head_hash"] is None
    assert _success(capsys, ["search-reviewed", str(catalogue), str(initial), "--tag", "topic:robotique"])["count"] == 0
    written = _success(capsys, [
        "review-tag", str(report_path), str(initial), "--tag", "topic:robotique",
        "--decision", "accept", "--actor", "fixture:reviewer", "--reason", "Fixture text reviewed.",
        "--event-id", "native-text-e1", "--expected-head", "none", "--out", str(accepted),
    ])
    assert written["event_created"] is True and written["event_count"] == 1
    saved = json.loads(accepted.read_text(encoding="utf-8"))
    assert saved["events"][0]["report_hash"] == hash_input(enriched)
    projected = _success(capsys, ["review-view", str(catalogue), str(accepted)])
    topic = next(tag for tag in projected["assets"][0]["tags"] if (tag["namespace"], tag["value"]) == ("topic", "robotique"))
    assert topic["status"] == "accepted" and topic["decision"]["event_id"] == "native-text-e1"
    assert any(ref.endswith("pdf:page:1") for ref in topic["evidence_refs"])
    found = _success(capsys, ["search-reviewed", str(catalogue), str(accepted), "--tag", "topic:robotique"])
    assert found["count"] == 1 and found["matches"][0]["report_hash"] == hash_input(enriched)
    assert {path: path.read_bytes() for path in originals} == originals

    # Same source, revision and proposed tag, but a different exact extraction.
    inspection = json.loads(inspection_path.read_text(encoding="utf-8"))
    changed_extraction = _write_json(tmp_path / "extraction2.json", _extraction(inspection, b"Un ROBOT modifie.\n\fUn jardin.\n\f"))
    changed = _success(capsys, _enrich_args(inspection_path, changed_extraction, topics_path))
    assert changed["input_hash"] != enriched["input_hash"]
    _write_json(catalogue, [changed])
    view = _success(capsys, ["review-view", str(catalogue), str(accepted)])
    current_topic = next(tag for tag in view["assets"][0]["tags"] if (tag["namespace"], tag["value"]) == ("topic", "robotique"))
    assert current_topic["status"] == "proposed"
    assert view["unapplied_events"][0]["reason"] == "report_changed"
    assert _success(capsys, ["search-reviewed", str(catalogue), str(accepted), "--tag", "topic:robotique"])["count"] == 0
