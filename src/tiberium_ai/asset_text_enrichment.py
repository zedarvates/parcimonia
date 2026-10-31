"""Link native text observations to proposed asset tags and their source spans.

This step reuses an existing extraction record; it never runs a native tool.
Native predictions and supplied records are not authenticated source truth.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from typing import Any

from .asset_inspection import _lexical_topic_matches
from .asset_tag_journal import _validate_report_json, validated_review_report_hash
from .text_evidence import parse_pdf_text
from .verification import hash_input

__all__ = ["enrich_asset_with_text"]

_EXTRACTION_FIELDS = {
    "schema", "source", "input_hash", "sample_sha256", "source_complete",
    "backend", "status", "text", "evidence", "coverage", "reason_codes",
    "native_calls", "elapsed_ms", "limits",
}
_CALL_FIELDS = {
    "phase", "status", "returncode", "stdout_sha256", "stderr_sha256",
    "stdout_complete", "stderr_complete", "elapsed_ms", "started", "error",
}


def _object(value: Any, fields: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{label} must contain exactly {sorted(fields)}.")


def _hash(value: Any, label: str) -> None:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be lowercase SHA-256.")


def _elapsed(value: Any) -> None:
    if type(value) not in (int, float) or value < 0:
        raise ValueError("Elapsed time must be a finite nonnegative number.")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("Elapsed time must be a finite nonnegative number.")


def _validate_extraction(extraction: Any, inspection: dict[str, Any]) -> None:
    _validate_report_json(extraction)
    _object(extraction, _EXTRACTION_FIELDS, "text extraction")
    if extraction["schema"] != "parcimonia.asset-text-extraction/v1":
        raise ValueError("Unsupported extraction schema.")
    if extraction["source"] != inspection["source"]:
        raise ValueError("Extraction and inspection must name the exact same source.")
    _object(extraction["source"], {"id", "revision", "filename"}, "extraction source")
    _hash(extraction["input_hash"], "extraction.input_hash")
    _hash(extraction["sample_sha256"], "extraction.sample_sha256")
    if (
        extraction["status"] != "completed" or extraction["source_complete"] is not True
        or inspection["sample"]["complete"] is not True
        or extraction["sample_sha256"] != inspection["sample"]["sha256"]
    ):
        raise ValueError("A completed extraction and complete matching source are required.")
    text = extraction["text"]
    if type(text) is not str or len(text.encode("utf-8")) > 262144:
        raise ValueError("Extracted text must fit the 256 KiB UTF-8 budget.")
    if any((ord(char) < 32 and char not in "\t\n\r\f") or 127 <= ord(char) <= 159 for char in text):
        raise ValueError("Extracted text contains unsupported controls.")
    backend = extraction["backend"]
    _object(backend, {"id", "version", "executable", "executable_sha256", "language", "weights_hash"}, "backend")
    if type(backend["id"]) is not str or backend["id"] not in {"tesseract", "pdftotext"}:
        raise ValueError("Unsupported text backend.")
    for field in ("version", "executable"):
        if type(backend[field]) is not str or not backend[field] or backend[field] != backend[field].strip():
            raise ValueError("Completed extraction must identify its declared native backend.")
    _hash(backend["executable_sha256"], "backend.executable_sha256")
    if backend["weights_hash"] is not None:
        raise ValueError("This backend contract does not attest weights.")
    if backend["id"] == "tesseract":
        if type(backend["language"]) is not str or not backend["language"]:
            raise ValueError("OCR language must be declared.")
    elif backend["language"] is not None:
        raise ValueError("Embedded PDF extraction does not declare an OCR language.")
    _elapsed(extraction["elapsed_ms"])
    if type(extraction["reason_codes"]) is not list or any(type(item) is not str for item in extraction["reason_codes"]):
        raise ValueError("Extraction reasons must be strings.")
    if type(extraction["limits"]) is not dict:
        raise ValueError("Extraction limits must be recorded.")
    calls = extraction["native_calls"]
    if type(calls) is not list or len(calls) != 2:
        raise ValueError("Expected exactly the version and extraction native calls.")
    for phase, call in zip(("version", "extract"), calls):
        _object(call, _CALL_FIELDS, "native call")
        if (
            call["phase"] != phase or call["status"] != "completed"
            or type(call["returncode"]) is not int or call["returncode"] != 0
            or call["stdout_complete"] is not True or call["stderr_complete"] is not True
            or call["started"] is not True or call["error"] is not None
        ):
            raise ValueError("Native call provenance must describe complete successful calls.")
        _hash(call["stdout_sha256"], "stdout_sha256")
        _hash(call["stderr_sha256"], "stderr_sha256")
        _elapsed(call["elapsed_ms"])
    evidence = extraction["evidence"]
    if type(evidence) is not list:
        raise ValueError("Text evidence must be an array.")
    if backend["id"] == "pdftotext":
        if inspection["format"]["detected"] != "pdf":
            raise ValueError("PDF text must bind a PDF inspection.")
        coverage = extraction["coverage"]
        _object(coverage, {"pages_requested", "pages_returned", "document_complete"}, "PDF coverage")
        requested = coverage["pages_requested"]
        if type(requested) is not list or len(requested) != 2 or type(requested[0]) is not int or requested[0] != 1:
            raise ValueError("Unsupported PDF page request.")
        expected = parse_pdf_text(text.encode("utf-8"), max_pages=requested[1])
        if hash_input(evidence) != hash_input(expected["evidence"]) or hash_input(coverage) != hash_input(expected["coverage"]):
            raise ValueError("PDF evidence must describe the exact supplied text and page scope.")
        return
    if inspection["format"]["detected"] not in {"png", "jpeg"}:
        raise ValueError("OCR must bind a supported image inspection.")
    if extraction["coverage"] != {"selected_image": 1, "document_complete": "not_established"} or type(extraction["coverage"].get("selected_image")) is not int:
        raise ValueError("Unsupported OCR image scope.")
    dimensions = {item.get("name"): item.get("value") for item in inspection["metadata"] if type(item) is dict}
    width, height = dimensions.get("width"), dimensions.get("height")
    if type(width) is not int or type(height) is not int or min(width, height) <= 0 or width * height > 4_000_000:
        raise ValueError("OCR source dimensions must be known and within the pixel budget.")
    if len(evidence) > 512:
        raise ValueError("OCR evidence exceeds 512 words.")
    cursor = 0
    for index, item in enumerate(evidence, start=1):
        _object(item, {"id", "kind", "page", "bbox", "char_range", "reported_score", "score_status"}, "OCR word")
        if item["id"] != f"ocr:word:{index}" or item["kind"] != "ocr_word" or type(item["page"]) is not int or item["page"] != 1:
            raise ValueError("OCR words must identify the selected image in order.")
        box, span = item["bbox"], item["char_range"]
        if type(box) is not list or len(box) != 4 or any(type(value) is not int for value in box):
            raise ValueError("OCR boxes must contain four integers.")
        left, top, box_width, box_height = box
        if min(left, top) < 0 or min(box_width, box_height) <= 0 or left + box_width > width or top + box_height > height:
            raise ValueError("OCR evidence falls outside its source image.")
        if type(span) is not list or len(span) != 2 or any(type(value) is not int for value in span) or not cursor <= span[0] < span[1] <= len(text):
            raise ValueError("Invalid OCR character range.")
        if text[cursor:span[0]] not in ({""} if index == 1 else {" ", "\n"}):
            raise ValueError("OCR text must reconstruct the supplied word spans.")
        word = text[span[0]:span[1]]
        if word != word.strip() or any(char in word for char in "\t\n\r\f"):
            raise ValueError("OCR word spans must contain word text.")
        _elapsed(item["reported_score"])
        if item["reported_score"] > 100 or item["score_status"] != "uncalibrated":
            raise ValueError("OCR scores must remain uncalibrated native values in 0..100.")
        cursor = span[1]
    if cursor != len(text):
        raise ValueError("OCR text must be fully covered by words and separators.")


def enrich_asset_with_text(
    inspection: dict[str, Any], extraction: dict[str, Any], *,
    topic_terms: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Create a reviewable enriched report from an exact existing extraction."""
    base_hash = validated_review_report_hash(inspection)
    if inspection["analyser"] != {"id": "asset-inspection", "version": "1"}:
        raise ValueError("Start enrichment from the original deterministic inspection.")
    _validate_extraction(extraction, inspection)
    extraction_hash = hash_input(extraction)
    text = extraction["text"]
    matches = _lexical_topic_matches(text, topic_terms, complete=True)
    result = deepcopy(inspection)
    result["analyser"] = {"id": "asset-text-enrichment", "version": "1"}
    result["input_hash"] = hash_input({"base_report_hash": base_hash, "extraction_report_hash": extraction_hash, "topic_terms": topic_terms})
    summary_id = f"extract:{extraction_hash}:summary"
    summary = {
        "id": summary_id, "kind": "native_text_extraction", "extraction_hash": extraction_hash,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "backend": deepcopy(extraction["backend"]), "coverage": deepcopy(extraction["coverage"]),
        "source_sha256": extraction["sample_sha256"], "indexing": "unicode_codepoints",
    }
    result["evidence"].append(summary)
    result["metadata"].append({"name": "text_extraction", "value": {"report_hash": extraction_hash, "text_characters": len(text), "native_calls": len(extraction["native_calls"]), "elapsed_ms": extraction["elapsed_ms"]}, "basis": "native_tool_observation", "evidence_ref": summary_id})
    retained: set[str] = set()
    for index, label, start, end in matches:
        refs = []
        for item in extraction["evidence"]:
            first, last = item["char_range"]
            if last > start and first < end:
                new_id = f"extract:{extraction_hash}:{item['id']}"
                refs.append(new_id)
                if new_id not in retained:
                    result["evidence"].append(dict(deepcopy(item), id=new_id))
                    retained.add(new_id)
        if not refs:
            raise ValueError("A proposed topic must be supported by native text spans.")
        match_id = f"extract:{extraction_hash}:topic:{index}"
        result["evidence"].append({"id": match_id, "kind": "extracted_text_lexical_match", "char_range": [start, end], "extraction_hash": extraction_hash, "source_evidence_refs": refs, "indexing": "unicode_codepoints"})
        result["tag_proposals"].append({"namespace": "topic", "value": label, "status": "proposed", "basis": "ocr_lexical_hint" if extraction["backend"]["id"] == "tesseract" else "embedded_text_lexical_hint", "evidence_refs": [summary_id, match_id, *refs]})
    if text.strip():
        if "text" not in result["modalities"]:
            result["modalities"].append("text")
        result["tag_proposals"].append({"namespace": "modality", "value": "text", "status": "proposed", "basis": "native_text_candidate", "evidence_refs": [summary_id]})
    result["status"] = "partial"
    result["reason_codes"] = sorted(set(result["reason_codes"]) | {"extracted_text_scope_limited"} | set(extraction["reason_codes"]))
    result["limits"].update({"semantic_content": "not_assessed_extracted_text_lexical_hints_only", "native_text_backend": extraction["backend"]["id"], "native_text_tool_calls": len(extraction["native_calls"]), "model_calls": None if extraction["backend"]["id"] == "tesseract" else 0, "native_text_quality": "not_calibrated", "extraction_sources": "caller_supplied_unverified"})
    validated_review_report_hash(result)
    return result
