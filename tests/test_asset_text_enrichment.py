"""Enrichment contract fixtures exercise attribution, not native OCR accuracy.

The parsers consume authored native-output fixtures. Tool identities and call
records are declarations for protocol tests; no executable is read or run.
The PNG is the demo's valid one-pixel image, so authored word boxes overlap.
The PDF source is a signature fixture, not a claim of a rendered document.
"""

from copy import deepcopy
import hashlib

import pytest

from examples.asset_catalog_demo import _png
from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import (
    append_tag_decision,
    create_tag_journal,
    validated_review_report_hash,
)
from tiberium_ai.asset_tag_review import project_tag_reviews, search_reviewed_assets
from tiberium_ai.asset_text_enrichment import enrich_asset_with_text
from tiberium_ai.text_evidence import parse_pdf_text, parse_tesseract_tsv
from tiberium_ai.verification import hash_input


PDF_SOURCE = b"%PDF-1.4\nprotocol fixture; no native tool is invoked\n"
PDF_TEXT = "ROBOT en atelier.\n\fUn jardin.\n\f".encode("utf-8")
TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t99.25\tÉcole\n"
    "5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t74.5\tROBOT\n"
    "5\t1\t1\t1\t2\t1\t0\t0\t1\t1\t0\tjardin\n"
).encode("utf-8")
TOPICS = {"robotique": ["robot"], "jardinage": ["jardin"], "absent": ["océan"]}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _call(phase, stdout):
    return {
        "phase": phase, "status": "completed", "returncode": 0,
        "stdout_sha256": _sha(stdout), "stderr_sha256": _sha(b""),
        "stdout_complete": True, "stderr_complete": True, "started": True,
        "error": None, "elapsed_ms": 0.25,
    }


def _fixture(backend="pdftotext", *, payload=None, complete=True):
    is_pdf = backend == "pdftotext"
    data = PDF_SOURCE if is_pdf else _png()
    inspection = inspect_asset(
        data, filename="fixture.pdf" if is_pdf else "fixture.png",
        source_id="fixture:extraction-protocol", revision="fixture-v1",
        complete=complete, **({} if complete else {"total_bytes": len(data) + 1}),
    )
    payload = (PDF_TEXT if is_pdf else TSV) if payload is None else payload
    parsed = parse_pdf_text(payload, max_pages=3) if is_pdf else parse_tesseract_tsv(payload, width=1, height=1)
    version = f"{backend} fixture-version-not-an-installed-tool"
    extraction = {
        "schema": "parcimonia.asset-text-extraction/v1",
        "source": deepcopy(inspection["source"]),
        "input_hash": hash_input({"fixture": backend, "page_limit": 3}),
        "sample_sha256": _sha(data), "source_complete": True,
        "backend": {
            "id": backend, "version": version,
            "executable": f"/declared-fixture-only/{backend}",
            "executable_sha256": _sha(b"declared fixture identity, not executable bytes"),
            "language": None if is_pdf else "eng", "weights_hash": None,
        },
        "status": "completed", "text": parsed["text"],
        "evidence": parsed["evidence"], "coverage": parsed["coverage"],
        "reason_codes": ["protocol_fixture_not_native_quality_evidence"],
        "native_calls": [_call("version", version.encode()), _call("extract", payload)],
        "elapsed_ms": 0.5,
        "limits": {"fixture": "authored_protocol_only", "ocr_scores": "uncalibrated"},
    }
    return inspection, extraction


def _enriched(backend="pdftotext", *, topics=TOPICS):
    inspection, extraction = _fixture(backend)
    return inspection, extraction, enrich_asset_with_text(inspection, extraction, topic_terms=topics)


def _topics(report):
    return {tag["value"]: tag for tag in report["tag_proposals"] if tag["namespace"] == "topic"}


def _evidence(report):
    return {item["id"]: item for item in report["evidence"]}


def _summary(report):
    return next(item for item in report["evidence"] if item["kind"] == "native_text_extraction")


@pytest.mark.parametrize("backend,format_name", [("pdftotext", "pdf"), ("tesseract", "png")])
def test_enrichment_preserves_source_format_and_adds_only_proposed_text_topics(backend, format_name):
    original, extraction, report = _enriched(backend)
    assert report["schema"] == "parcimonia.asset-inspection/v1"
    assert report["analyser"] == {"id": "asset-text-enrichment", "version": "1"}
    assert report["source"] == original["source"]
    assert report["sample"] == original["sample"]
    assert report["format"] == original["format"]
    assert report["format"]["detected"] == format_name
    assert set(original["modalities"]) <= set(report["modalities"])
    assert "text" in report["modalities"]
    assert all(tag["status"] == "proposed" for tag in report["tag_proposals"])
    assert not any(tag["namespace"] == "format" and tag["value"] == "text" for tag in report["tag_proposals"])
    assert {(tag["namespace"], tag["value"]) for tag in original["tag_proposals"]} <= {
        (tag["namespace"], tag["value"]) for tag in report["tag_proposals"]
    }
    assert set(_topics(report)) == {"robotique", "jardinage"}
    assert report["mode"] == "shadow" and report["status"] == "partial"
    assert "extracted_text_scope_limited" in report["reason_codes"]
    assert extraction["reason_codes"][0] in report["reason_codes"]
    assert validated_review_report_hash(report) == hash_input(report)
    assert search_asset_reports([report], tags=["topic:robotique"])["count"] == 1
    journal = create_tag_journal()
    assert search_reviewed_assets([report], journal, tags=["topic:robotique"])["count"] == 0
    assert search_reviewed_assets([report], journal, tags=["topic:robotique"], states=["proposed"])["count"] == 1


def test_pdf_lexical_matches_link_exact_unicode_ranges_to_their_native_pages():
    _, extraction, report = _enriched()
    evidence, topics = _evidence(report), _topics(report)
    for topic, word, page in (("robotique", "ROBOT", 1), ("jardinage", "jardin", 2)):
        tag = topics[topic]
        assert tag["basis"] == "embedded_text_lexical_hint"
        linked = [evidence[ref] for ref in tag["evidence_refs"]]
        match = next(item for item in linked if item["kind"] == "extracted_text_lexical_match")
        start = extraction["text"].index(word)
        assert match["char_range"] == [start, start + len(word)]
        assert match["indexing"] == "unicode_codepoints"
        pages = [item for item in linked if item["kind"] == "pdf_page_text"]
        assert len(pages) == 1 and pages[0]["page"] == page
        original = extraction["evidence"][page - 1]
        assert {key: value for key, value in pages[0].items() if key != "id"} == {
            key: value for key, value in original.items() if key != "id"
        }
        assert match["source_evidence_refs"] == [pages[0]["id"]]
        assert pages[0]["char_range"][0] <= start < start + len(word) <= pages[0]["char_range"][1]


def test_ocr_matches_keep_exact_word_boxes_and_uncalibrated_scores():
    _, extraction, report = _enriched("tesseract")
    assert extraction["text"] == "École ROBOT\njardin"
    evidence = _evidence(report)
    for topic, word_index in (("robotique", 1), ("jardinage", 2)):
        tag = _topics(report)[topic]
        assert tag["basis"] == "ocr_lexical_hint"
        word = next(evidence[ref] for ref in tag["evidence_refs"] if evidence[ref]["kind"] == "ocr_word")
        native = extraction["evidence"][word_index]
        assert word["bbox"] == native["bbox"] == [0, 0, 1, 1]
        assert word["char_range"] == native["char_range"]
        assert word["page"] == 1
        assert word["reported_score"] == native["reported_score"]
        assert word["score_status"] == "uncalibrated"
        assert "confidence" not in word and "probability" not in word
    assert _topics(report)["robotique"]["evidence_refs"][2].endswith("ocr:word:2")


@pytest.mark.parametrize("backend,model_calls", [("pdftotext", 0), ("tesseract", None)])
def test_limits_retain_backend_cost_and_quality_uncertainty(backend, model_calls):
    _, extraction, report = _enriched(backend)
    summary = _summary(report)
    assert summary["backend"] == extraction["backend"]
    assert summary["coverage"] == extraction["coverage"]
    assert summary["source_sha256"] == report["sample"]["sha256"]
    assert summary["text_sha256"] == _sha(extraction["text"].encode())
    assert summary["extraction_hash"] == hash_input(extraction)
    assert summary["coverage"]["document_complete"] == "not_established"
    assert report["limits"]["native_text_backend"] == backend
    assert report["limits"]["native_text_tool_calls"] == 2
    if model_calls is None:
        assert report["limits"]["model_calls"] is None
    else:
        assert type(report["limits"]["model_calls"]) is int
        assert report["limits"]["model_calls"] == model_calls
    assert report["limits"]["native_text_quality"] == "not_calibrated"
    assert report["limits"]["semantic_content"] == "not_assessed_extracted_text_lexical_hints_only"
    assert report["limits"]["extraction_sources"] == "caller_supplied_unverified"


@pytest.mark.parametrize("backend,payload", [("pdftotext", b""), ("tesseract", TSV.split(b"\n", 1)[0] + b"\n")])
def test_empty_success_has_no_text_modality_or_claim_of_absence(backend, payload):
    original, extraction = _fixture(backend, payload=payload)
    report = enrich_asset_with_text(original, extraction, topic_terms=TOPICS)
    assert _topics(report) == {}
    assert report["modalities"] == original["modalities"]
    assert not any(tag["namespace"] == "modality" and tag["value"] == "text" for tag in report["tag_proposals"])
    assert _summary(report)["coverage"]["document_complete"] == "not_established"
    assert report["status"] == "partial"


def test_lexicon_is_literal_and_does_not_turn_negation_into_a_semantic_judgment():
    original, extraction = _fixture(payload=b"Pas de robot; robotique seule.\f")
    report = enrich_asset_with_text(original, extraction, topic_terms={"robotique": ["robot"], "objet": ["drone"]})
    assert set(_topics(report)) == {"robotique"}
    assert _topics(report)["robotique"]["status"] == "proposed"
    assert "not_assessed" in report["limits"]["semantic_content"]


def test_enrichment_without_lexicon_adds_text_observation_but_no_topics():
    original, extraction = _fixture()
    report = enrich_asset_with_text(original, extraction)
    assert _topics(report) == {}
    assert "text" in report["modalities"]
    assert any(item["kind"] == "native_text_extraction" for item in report["evidence"])


@pytest.mark.parametrize("backend", ["pdftotext", "tesseract"])
@pytest.mark.parametrize("prefix", ["glTF", "fLaC", "%PDF-"])
def test_native_text_signature_prefix_keeps_topic_and_exact_source_span(backend, prefix):
    words = [prefix, "école", "ROBOT"]
    text = " ".join(words)
    if backend == "pdftotext":
        payload = (text + "\n\f").encode("utf-8")
    else:
        rows = [
            f"5\t1\t1\t1\t1\t{index}\t0\t0\t1\t1\t90\t{word}\n"
            for index, word in enumerate(words, start=1)
        ]
        payload = TSV.split(b"\n", 1)[0] + b"\n" + "".join(rows).encode("utf-8")
    original, extraction = _fixture(backend, payload=payload)
    report = enrich_asset_with_text(original, extraction, topic_terms={"robotique": ["robot"]})
    assert set(_topics(report)) == {"robotique"}
    tag = _topics(report)["robotique"]
    assert tag["status"] == "proposed"
    assert report["format"] == original["format"]
    assert set(report["modalities"]) == set(original["modalities"]) | {"text"}
    evidence = _evidence(report)
    match = next(evidence[ref] for ref in tag["evidence_refs"] if evidence[ref]["kind"] == "extracted_text_lexical_match")
    start = len(prefix) + len(" école ")
    assert match["char_range"] == [start, start + len("ROBOT")]
    assert match["indexing"] == "unicode_codepoints"
    assert extraction["text"][start:start + len("ROBOT")] == "ROBOT"
    source = [evidence[ref] for ref in match["source_evidence_refs"]]
    assert len(source) == 1 and source[0]["page"] == 1
    if backend == "tesseract":
        assert source[0]["kind"] == "ocr_word"
        assert source[0]["char_range"] == match["char_range"]
        assert source[0]["bbox"] == [0, 0, 1, 1]
    else:
        assert source[0]["kind"] == "pdf_page_text"
        assert source[0]["char_range"] == [0, len(text) + 1]


def test_phrase_match_can_link_two_ocr_words_without_losing_their_separate_zones():
    original, extraction = _fixture("tesseract")
    report = enrich_asset_with_text(original, extraction, topic_terms={"education": ["École ROBOT"]})
    tag = _topics(report)["education"]
    evidence = _evidence(report)
    match = next(evidence[ref] for ref in tag["evidence_refs"] if evidence[ref]["kind"] == "extracted_text_lexical_match")
    assert match["char_range"] == [0, len("École ROBOT")]
    words = [evidence[ref] for ref in match["source_evidence_refs"]]
    assert [word["char_range"] for word in words] == [[0, 5], [6, 11]]
    assert [word["bbox"] for word in words] == [[0, 0, 1, 1], [0, 0, 1, 1]]
    assert all(word["kind"] == "ocr_word" for word in words)


def test_shared_native_page_evidence_is_unique_when_several_topics_overlap_it():
    original, extraction = _fixture()
    report = enrich_asset_with_text(original, extraction, topic_terms={"robotique": ["robot"], "atelier": ["atelier"]})
    evidence = _evidence(report)
    assert len(evidence) == len(report["evidence"])
    page_refs = []
    for tag in _topics(report).values():
        page_refs.extend(ref for ref in tag["evidence_refs"] if evidence[ref]["kind"] == "pdf_page_text")
    assert len(page_refs) == 2 and page_refs[0] == page_refs[1]


def test_both_inputs_remain_equal_and_all_returned_containers_are_independent():
    original, extraction = _fixture("tesseract")
    before_original, before_extraction, topics = deepcopy(original), deepcopy(extraction), deepcopy(TOPICS)
    report = enrich_asset_with_text(original, extraction, topic_terms=topics)
    assert original == before_original and extraction == before_extraction and topics == TOPICS
    returned_before_mutation = deepcopy(report)
    original["source"]["filename"] = "changed.png"
    original["metadata"].clear()
    extraction["backend"]["version"] = "changed"
    extraction["coverage"]["selected_image"] = 99
    extraction["evidence"][1]["bbox"][0] = 999
    extraction["native_calls"][0]["elapsed_ms"] = 100
    topics["robotique"].append("changed")
    assert report == returned_before_mutation
    fresh_original, fresh_extraction = _fixture("tesseract")
    second = enrich_asset_with_text(fresh_original, fresh_extraction, topic_terms=TOPICS)
    report["sample"]["sha256"] = "f" * 64
    report["source"]["id"] = "changed"
    _summary(report)["backend"]["version"] = "changed"
    _summary(report)["coverage"]["selected_image"] = 2
    next(item for item in report["evidence"] if item["kind"] == "ocr_word")["bbox"][0] = 22
    report["tag_proposals"][-1]["evidence_refs"].append("foreign")
    assert second == returned_before_mutation
    assert fresh_original == before_original and fresh_extraction == before_extraction


@pytest.mark.parametrize("field,value", [("id", "other"), ("revision", "fixture-v2"), ("filename", "renamed.pdf")])
def test_each_source_identity_component_must_match_exactly(field, value):
    original, extraction = _fixture()
    extraction["source"][field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction, topic_terms=TOPICS)


@pytest.mark.parametrize("field,value", [
    ("sample_sha256", "f" * 64), ("source_complete", False), ("source_complete", 1),
    ("status", "failed"), ("status", "indeterminate"), ("status", "unavailable"),
])
def test_incomplete_or_nonmatching_extractions_are_refused(field, value):
    original, extraction = _fixture()
    extraction[field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction, topic_terms=TOPICS)


def test_matching_sample_digest_does_not_make_a_prefix_a_complete_source():
    original, extraction = _fixture(complete=False)
    assert original["sample"]["sha256"] == extraction["sample_sha256"]
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction, topic_terms=TOPICS)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("field,value", [
    ("status", "timeout"), ("status", "output_limit"), ("returncode", 1),
    ("returncode", False), ("returncode", None), ("stdout_complete", False),
    ("stdout_complete", 1), ("stderr_complete", False), ("started", False),
    ("error", "pipe_read_error"), ("elapsed_ms", -1), ("elapsed_ms", True),
    ("stdout_sha256", "not-a-hash"),
])
def test_both_native_calls_must_record_complete_zero_exit_observations(index, field, value):
    original, extraction = _fixture()
    extraction["native_calls"][index][field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction)


@pytest.mark.parametrize("change", ["missing_call", "extra_call", "reverse_phases", "extra_field"])
def test_native_call_sequence_is_closed_and_exactly_version_then_extract(change):
    original, extraction = _fixture()
    if change == "missing_call":
        extraction["native_calls"].pop()
    elif change == "extra_call":
        extraction["native_calls"].append(deepcopy(extraction["native_calls"][-1]))
    elif change == "reverse_phases":
        extraction["native_calls"].reverse()
    else:
        extraction["native_calls"][0]["stdout"] = "raw output is not part of this record"
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction)


@pytest.mark.parametrize("field,value", [
    ("schema", "foreign/v1"), ("input_hash", "A" * 64), ("elapsed_ms", -1),
    ("elapsed_ms", True), ("elapsed_ms", float("nan")), ("elapsed_ms", float("inf")),
    ("text", None), ("text", "a" * 262145), ("text", "bad\x00text"),
    ("reason_codes", [1]), ("limits", []),
])
def test_invalid_extraction_scalar_contracts_are_refused(field, value):
    original, extraction = _fixture()
    extraction[field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction)


class _ForeignDict(dict):
    pass


@pytest.mark.parametrize("foreign", [b"raw", (1, 2), {1, 2}, object(), _ForeignDict(a=1), {1: "numeric key"}, "\ud800"])
def test_foreign_json_nested_in_declared_limits_is_refused(foreign):
    original, extraction = _fixture()
    extraction["limits"]["foreign"] = foreign
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction)


@pytest.mark.parametrize("field,value", [
    ("id", "unsupported"), ("id", []), ("version", ""), ("executable", " tool "),
    ("executable_sha256", "g" * 64), ("language", "eng"), ("weights_hash", "a" * 64),
])
def test_pdf_backend_identity_and_declared_capability_are_validated(field, value):
    original, extraction = _fixture()
    extraction["backend"][field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction)


@pytest.mark.parametrize("change", ["extra_top_level", "extra_source", "extra_backend", "missing_field"])
def test_extraction_records_have_closed_shapes(change):
    original, extraction = _fixture()
    if change == "extra_top_level":
        extraction["foreign"] = 1
    elif change == "extra_source":
        extraction["source"]["uri"] = "foreign"
    elif change == "extra_backend":
        extraction["backend"]["confidence"] = 1
    else:
        del extraction["evidence"]
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction)


@pytest.mark.parametrize("change", [
    "outside_box", "negative_box", "empty_box", "bool_box", "span_overrun", "span_negative",
    "overlap", "missing_word", "unproven_suffix", "unproven_prefix", "bad_separator",
    "foreign_id", "foreign_page", "calibrated_score", "score_over_100", "extra_word_field",
    "complete_claim", "boolean_image",
])
def test_forged_ocr_geometry_spans_scores_or_scope_are_rejected(change):
    original, extraction = _fixture("tesseract")
    word = extraction["evidence"][1]
    if change == "outside_box":
        word["bbox"] = [1, 0, 1, 1]
    elif change == "negative_box":
        word["bbox"] = [-1, 0, 1, 1]
    elif change == "empty_box":
        word["bbox"] = [0, 0, 0, 1]
    elif change == "bool_box":
        word["bbox"] = [False, 0, 1, 1]
    elif change == "span_overrun":
        word["char_range"][1] = len(extraction["text"]) + 1
    elif change == "span_negative":
        word["char_range"][0] = -1
    elif change == "overlap":
        word["char_range"][0] = 0
    elif change == "missing_word":
        extraction["evidence"].pop()
    elif change == "unproven_suffix":
        extraction["text"] += " drone"
    elif change == "unproven_prefix":
        extraction["text"] = " " + extraction["text"]
    elif change == "bad_separator":
        extraction["text"] = extraction["text"].replace(" ", "|")
    elif change == "foreign_id":
        word["id"] = "ocr:word:99"
    elif change == "foreign_page":
        word["page"] = 2
    elif change == "calibrated_score":
        word["score_status"] = "calibrated"
    elif change == "score_over_100":
        word["reported_score"] = 100.1
    elif change == "extra_word_field":
        word["confidence"] = 0.99
    elif change == "complete_claim":
        extraction["coverage"]["document_complete"] = True
    else:
        extraction["coverage"]["selected_image"] = True
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction, topic_terms=TOPICS)


@pytest.mark.parametrize("change", ["page_count", "page_number", "page_span", "page_id", "extra_page", "empty_evidence", "complete_claim", "zero_start", "boolean_end", "text_changed"])
def test_forged_pdf_page_counts_ranges_and_unproven_text_are_rejected(change):
    original, extraction = _fixture()
    if change == "page_count":
        extraction["coverage"]["pages_returned"] = 7
    elif change == "page_number":
        extraction["evidence"][1]["page"] = 7
    elif change == "page_span":
        extraction["evidence"][0]["char_range"][1] += 1
    elif change == "page_id":
        extraction["evidence"][0]["id"] = "pdf:page:7"
    elif change == "extra_page":
        extraction["evidence"].append(deepcopy(extraction["evidence"][-1]))
    elif change == "empty_evidence":
        extraction["evidence"] = []
    elif change == "complete_claim":
        extraction["coverage"]["document_complete"] = True
    elif change == "zero_start":
        extraction["coverage"]["pages_requested"][0] = 0
    elif change == "boolean_end":
        extraction["coverage"]["pages_requested"][1] = True
    else:
        extraction["text"] += "unproven extra page text"
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction, topic_terms=TOPICS)


@pytest.mark.parametrize("backend,other_backend", [("pdftotext", "tesseract"), ("tesseract", "pdftotext")])
def test_backend_cannot_attach_its_observations_to_a_different_source_format(backend, other_backend):
    _, extraction = _fixture(backend)
    original, _ = _fixture(other_backend)
    extraction["source"] = deepcopy(original["source"])
    extraction["sample_sha256"] = original["sample"]["sha256"]
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction, topic_terms=TOPICS)


@pytest.mark.parametrize("analyser", [{"id": "asset-inspection", "version": "2"}, {"id": "foreign", "version": "1"}])
def test_unsupported_analysers_are_not_admitted_by_catalogue_or_enrichment(analyser):
    original, extraction = _fixture()
    original["analyser"] = analyser
    with pytest.raises(ValueError):
        validated_review_report_hash(original)
    with pytest.raises(ValueError):
        enrich_asset_with_text(original, extraction, topic_terms=TOPICS)


def test_enriched_analyser_is_explicitly_supported_but_cannot_be_enriched_twice():
    _, extraction, report = _enriched()
    assert validated_review_report_hash(report) == hash_input(report)
    with pytest.raises(ValueError):
        enrich_asset_with_text(report, extraction, topic_terms=TOPICS)


@pytest.mark.parametrize("change", ["proof", "backend_version", "configuration", "total_latency", "call_latency", "lexicon"])
def test_changed_extraction_evidence_configuration_or_latency_invalidates_old_review(change):
    original, extraction, report = _enriched()
    journal = append_tag_decision(
        create_tag_journal(), report, namespace="topic", value="robotique", action="accept",
        actor_id="fixture-reviewer", reason="Authored protocol fixture reviewed",
        event_id="enrichment-review-1", expected_head=None,
    )
    assert search_reviewed_assets([report], journal, tags=["topic:robotique"])["count"] == 1
    topics = deepcopy(TOPICS)
    if change == "proof":
        extraction["native_calls"][1]["stderr_sha256"] = _sha(b"additional declared diagnostic")
    elif change == "backend_version":
        extraction["backend"]["version"] += "-changed"
    elif change == "configuration":
        extraction["limits"]["configuration"] = "different bounded setting"
    elif change == "total_latency":
        extraction["elapsed_ms"] += 1
    elif change == "call_latency":
        extraction["native_calls"][1]["elapsed_ms"] += 1
    else:
        topics["robotique"].append("robotique")
    current = enrich_asset_with_text(original, extraction, topic_terms=topics)
    assert current["source"] == report["source"] and set(_topics(current)) == set(_topics(report))
    assert current["input_hash"] != report["input_hash"]
    assert validated_review_report_hash(current) != validated_review_report_hash(report)
    projected = project_tag_reviews([current], journal)
    assert projected["unapplied_events"] == [{
        "event_id": "enrichment-review-1",
        "source": {"id": original["source"]["id"], "revision": original["source"]["revision"]},
        "reason": "report_changed",
    }]
    topic = next(tag for tag in projected["assets"][0]["tags"] if tag["namespace"] == "topic" and tag["value"] == "robotique")
    assert topic["status"] == "proposed" and topic["decision"] is None
    assert search_reviewed_assets([current], journal, tags=["topic:robotique"])["count"] == 0
