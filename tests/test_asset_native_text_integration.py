"""Optional installed-tool checks on authored, dependency-free fixtures.

These checks exercise local backends without downloading a binary or language
data. Recognition of these simple fixtures does not qualify OCR generally.
"""

import hashlib
import os
from pathlib import Path
import shutil
import struct
import time

import pytest

from examples.native_text_demo import ocr_png_fixture, pdf_fixture
from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_text_enrichment import enrich_asset_with_text
from tiberium_ai.asset_text_extract import extract_asset_text
from tiberium_ai.native_process import run_bounded


def _installed_tool(name):
    executable = shutil.which(name)
    if executable is None:
        pytest.skip(f"Optional native integration requires installed {name}.")
    return str(Path(executable).resolve())


def _extract_and_enrich(data, backend, executable):
    filename = "native-fixture.png" if backend == "tesseract" else "native-fixture.pdf"
    identity = {"filename": filename, "source_id": f"native-test:{backend}", "revision": "v1"}
    inspection = inspect_asset(data, **identity)
    extraction = extract_asset_text(
        data, **identity, backend=backend, executable=executable,
        language="eng", max_pages=1, timeout_s=10.0,
    )
    assert extraction["status"] == "completed", extraction["reason_codes"]
    assert extraction["sample_sha256"] == hashlib.sha256(data).hexdigest()
    assert extraction["source_complete"] is True
    assert extraction["backend"]["executable"] == executable
    assert extraction["backend"]["weights_hash"] is None
    assert [call["phase"] for call in extraction["native_calls"]] == ["version", "extract"]
    assert all(
        call["status"] == "completed" and call["returncode"] == 0
        and call["stdout_complete"] and call["stderr_complete"]
        for call in extraction["native_calls"]
    )
    assert "ROBOT" in extraction["text"] and "GARDEN" in extraction["text"]
    assert extraction["coverage"]["document_complete"] == "not_established"

    enriched = enrich_asset_with_text(
        inspection, extraction,
        topic_terms={"robotique": ["robot"], "jardin": ["garden"]},
    )
    assert enriched["source"] == inspection["source"]
    assert enriched["sample"] == inspection["sample"]
    assert "text" in enriched["modalities"]
    evidence = {item["id"]: item for item in enriched["evidence"]}
    topics = {tag["value"]: tag for tag in enriched["tag_proposals"] if tag["namespace"] == "topic"}
    assert set(topics) == {"robotique", "jardin"}
    for topic, word in (("robotique", "ROBOT"), ("jardin", "GARDEN")):
        tag = topics[topic]
        assert tag["status"] == "proposed"
        linked = [evidence[reference] for reference in tag["evidence_refs"]]
        match = next(item for item in linked if item["kind"] == "extracted_text_lexical_match")
        start = extraction["text"].index(word)
        assert match["char_range"] == [start, start + len(word)]
        assert match["indexing"] == "unicode_codepoints"
        assert match["source_evidence_refs"]
        for reference in match["source_evidence_refs"]:
            native = evidence[reference]
            assert native in linked
            assert native["char_range"][0] <= start
            assert start + len(word) <= native["char_range"][1]
            assert any(
                {key: value for key, value in native.items() if key != "id"}
                == {key: value for key, value in original.items() if key != "id"}
                for original in extraction["evidence"]
            )

    search = search_asset_reports([enriched], tags=["topic:robotique", "topic:jardin"])
    assert search["count"] == 1
    assert search["matches"][0]["source"] == enriched["source"]
    assert search["matches"][0]["matched_tags"] == ["topic:jardin", "topic:robotique"]
    assert search["limits"]["tags"] == "proposals_only"
    assert search_asset_reports([enriched], tags=["topic:absent"])["count"] == 0
    return extraction, enriched


def test_installed_tesseract_fixture_keeps_word_boxes_through_search(tmp_path):
    executable = _installed_tool("tesseract")
    environment = os.environ.copy()
    environment.update({"OMP_THREAD_LIMIT": "1", "LC_ALL": "C"})
    languages = run_bounded(
        [executable, "--list-langs"], deadline=time.monotonic() + 5.0,
        max_stdout_bytes=16384, max_stderr_bytes=16384,
        cwd=str(tmp_path), env=environment,
    )
    assert languages["status"] == "completed" and languages["returncode"] == 0
    assert languages["stdout_complete"] and languages["stderr_complete"]
    listed = (languages["stdout"] + b"\n" + languages["stderr"]).decode("utf-8").splitlines()
    if "eng" not in {line.strip() for line in listed}:
        pytest.skip("Optional Tesseract integration requires installed eng language data.")

    data = ocr_png_fixture()
    extraction, enriched = _extract_and_enrich(data, "tesseract", executable)
    assert extraction["backend"]["language"] == "eng"
    assert enriched["format"]["detected"] == "png"
    width, height = struct.unpack(">II", data[16:24])
    for word in ("ROBOT", "GARDEN"):
        native = next(
            item for item in extraction["evidence"]
            if extraction["text"][slice(*item["char_range"])] == word
        )
        assert native["kind"] == "ocr_word" and native["page"] == 1
        left, top, box_width, box_height = native["bbox"]
        assert 0 <= left < left + box_width <= width
        assert 0 <= top < top + box_height <= height
        assert native["score_status"] == "uncalibrated"
        assert 0 <= native["reported_score"] <= 100


def test_installed_pdftotext_fixture_keeps_page_spans_through_search():
    executable = _installed_tool("pdftotext")
    extraction, enriched = _extract_and_enrich(pdf_fixture(), "pdftotext", executable)
    assert extraction["backend"]["language"] is None
    assert enriched["format"]["detected"] == "pdf"
    assert extraction["coverage"]["pages_requested"] == [1, 1]
    assert extraction["coverage"]["pages_returned"] == 1
    assert len(extraction["evidence"]) == 1
    page = extraction["evidence"][0]
    assert page["kind"] == "pdf_page_text" and page["page"] == 1
    page_text = extraction["text"][slice(*page["char_range"])]
    assert "ROBOT" in page_text and "GARDEN" in page_text
