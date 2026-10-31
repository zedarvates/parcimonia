"""Pure, bounded parsing of native OCR/PDF text and attributable spans.

These functions interpret supplied native output only. They do not start a
tool, read a source, calibrate a score or establish semantic source truth.
"""

from __future__ import annotations

import math
import re
from typing import Any

__all__ = ["MAX_OCR_WORDS", "parse_tesseract_tsv", "parse_pdf_text"]

MAX_OUTPUT_BYTES = 256 * 1024
MAX_TSV_ROWS = 10_000
MAX_OCR_WORDS = 512
_TSV_HEADER = (
    "level", "page_num", "block_num", "par_num", "line_num", "word_num",
    "left", "top", "width", "height", "conf", "text",
)
_INTEGER = re.compile(r"[0-9]{1,20}\Z", re.ASCII)
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z", re.ASCII)


def _decode(payload: Any, *, form_feed: bool) -> str:
    if type(payload) is not bytes or len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError("payload must be bytes containing at most 256 KiB.")
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Native text output must be valid UTF-8.") from exc
    allowed = "\t\n\r\f" if form_feed else "\t\n\r"
    if any((ord(char) < 32 and char not in allowed) or 127 <= ord(char) <= 159 for char in text):
        raise ValueError("Native text output contains unsupported control characters.")
    return text


def _dimension(value: Any, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer, not a boolean.")


def _integer(value: str) -> int:
    if _INTEGER.fullmatch(value) is None:
        raise ValueError("TSV index and box fields must be nonnegative ASCII integers.")
    return int(value)


def _score(value: str) -> float:
    if len(value) > 64 or _DECIMAL.fullmatch(value) is None:
        raise ValueError("TSV confidence must use a finite decimal representation.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("TSV confidence must be finite.")
    return result


def parse_tesseract_tsv(payload: bytes, *, width: int, height: int) -> dict[str, Any]:
    """Parse one selected image's Tesseract TSV without reordering its words.

    A word's reported native score is retained as uncalibrated metadata, never
    promoted to a probability. Unsupported fields, out-of-image boxes and
    non-increasing reading-order indices reject the entire response.
    """
    _dimension(width, "width")
    _dimension(height, "height")
    native = _decode(payload, form_feed=False)
    rows = native.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    if not rows or tuple(rows[0].removesuffix("\r").split("\t")) != _TSV_HEADER:
        raise ValueError("Tesseract TSV must have the exact supported header.")
    if len(rows) - 1 > MAX_TSV_ROWS:
        raise ValueError("Tesseract TSV exceeds the 10000-row budget.")

    fragments: list[str] = []
    evidence: list[dict[str, Any]] = []
    cursor = 0
    previous_order: tuple[int, ...] | None = None
    previous_line: tuple[int, ...] | None = None
    for row in rows[1:]:
        fields = row.removesuffix("\r").split("\t")
        if len(fields) != len(_TSV_HEADER):
            raise ValueError("Each Tesseract TSV row must contain exactly 12 fields.")
        numbers = [_integer(field) for field in fields[:10]]
        level, page, block, paragraph, line, word, left, top, box_width, box_height = numbers
        score, text = _score(fields[10]), fields[11]
        if not 1 <= level <= 5 or page != 1:
            raise ValueError("Only Tesseract levels 1..5 on selected image page 1 are supported.")
        hierarchy = (block, paragraph, line, word)
        active = level - 1
        if any(value == 0 for value in hierarchy[:active]) or any(value != 0 for value in hierarchy[active:]):
            raise ValueError("TSV hierarchy indices contradict their row level.")
        if left + box_width > width or top + box_height > height:
            raise ValueError("TSV bounding box falls outside the supplied image dimensions.")
        if level < 5:
            if score != -1 or text:
                raise ValueError("Non-word TSV rows must contain no text and score -1.")
            continue
        if not 0 <= score <= 100:
            raise ValueError("Word TSV scores must be within 0..100.")
        order = (page, block, paragraph, line, word)
        if previous_order is not None and order <= previous_order:
            raise ValueError("TSV word indices must increase in supplied reading order.")
        previous_order = order
        if not text:
            continue
        if text != text.strip() or "\r" in text:
            raise ValueError("TSV word text must be nonempty trimmed text without row controls.")
        if box_width == 0 or box_height == 0:
            raise ValueError("Nonempty TSV words must have positive box dimensions.")
        if len(evidence) >= MAX_OCR_WORDS:
            raise ValueError("OCR text exceeds the 512-word evidence budget.")
        line_key = (page, block, paragraph, line)
        if fragments:
            separator = " " if line_key == previous_line else "\n"
            fragments.append(separator)
            cursor += len(separator)
        start = cursor
        fragments.append(text)
        cursor += len(text)
        evidence.append({
            "id": f"ocr:word:{len(evidence) + 1}",
            "kind": "ocr_word",
            "page": 1,
            "bbox": [left, top, box_width, box_height],
            "char_range": [start, cursor],
            "reported_score": score,
            "score_status": "uncalibrated",
        })
        previous_line = line_key
    text = "".join(fragments)
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("Reconstructed OCR text exceeds the 256 KiB budget.")
    return {
        "text": text,
        "evidence": evidence,
        "coverage": {"selected_image": 1, "document_complete": "not_established"},
        "limitations": [
            "OCR words and reported scores are uncalibrated native predictions.",
            "Only the selected image page is represented; unseen frames or pages remain unknown.",
            "Reading-order reconstruction does not recognize objects, scenes or semantic negation.",
            "Responses exceeding 512 recognized words are refused without partial evidence.",
        ],
    }


def parse_pdf_text(payload: bytes, *, max_pages: int = 3) -> dict[str, Any]:
    """Retain native UTF-8 text and page spans using its form-feed delimiters.

    A terminal form feed and its following whitespace do not create another
    page. Text is preserved byte-for-byte after UTF-8 decoding; separator bytes
    need not belong to a page evidence span. Empty native output establishes no
    page count and never proves that the document contains no visible text.
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 8:
        raise ValueError("max_pages must be an integer from 1 to 8.")
    text = _decode(payload, form_feed=True)
    if not text:
        pages: list[str] = []
    else:
        pages = text.split("\f")
        if "\f" in text and not pages[-1].strip(" \t\r\n"):
            pages.pop()
    if len(pages) > max_pages:
        raise ValueError("Native PDF text contains more pages than requested.")
    evidence = []
    start = 0
    for page, content in enumerate(pages, start=1):
        end = start + len(content)
        evidence.append({
            "id": f"pdf:page:{page}", "kind": "pdf_page_text",
            "page": page, "char_range": [start, end],
        })
        start = end + 1
    return {
        "text": text,
        "evidence": evidence,
        "coverage": {
            "pages_requested": [1, max_pages],
            "pages_returned": len(pages),
            "document_complete": "not_established",
        },
        "limitations": [
            "Text covers returned requested pages only; total document page count remains unknown.",
            "Empty extracted text does not establish absence of visible or scanned content.",
            "Page spans use native form-feed boundaries; no OCR or page geometry is inferred.",
        ],
    }
