"""Contract tests for pure native text decoding and attributable evidence."""

from copy import deepcopy
import json

import pytest

from tiberium_ai.text_evidence import parse_pdf_text, parse_tesseract_tsv


HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def _row(text="robot", *, level=5, page=1, block=1, paragraph=1, line=1, word=1, left=10, top=20, width=30, height=10, score="93.25"):
    return "\t".join(str(value) for value in (level, page, block, paragraph, line, word, left, top, width, height, score, text))


def _payload(*rows):
    return (HEADER + "\n" + "\n".join(rows) + ("\n" if rows else "")).encode("utf-8")


def test_ocr_reconstructs_reading_order_and_unicode_character_spans():
    result = parse_tesseract_tsv(_payload(
        _row("été", score="0"), _row("rêve", word=2, left=45, score="100"),
        _row("robot", line=2, word=1, top=40),
    ), width=100, height=100)
    assert result["text"] == "été rêve\nrobot"
    assert [word["char_range"] for word in result["evidence"]] == [[0, 3], [4, 8], [9, 14]]
    assert [result["text"][slice(*item["char_range"])] for item in result["evidence"]] == ["été", "rêve", "robot"]
    assert result["evidence"][1]["bbox"] == [45, 20, 30, 10]
    assert [item["reported_score"] for item in result["evidence"]] == [0.0, 100.0, 93.25]
    assert {item["score_status"] for item in result["evidence"]} == {"uncalibrated"}
    assert result["coverage"]["document_complete"] == "not_established"
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_nonword_rows_are_validated_but_never_become_recognized_text():
    page = _row("", level=1, block=0, paragraph=0, line=0, word=0, left=0, top=0, width=100, height=100, score="-1")
    result = parse_tesseract_tsv(_payload(page, _row("robot")), width=100, height=100)
    assert result["text"] == "robot"
    assert len(result["evidence"]) == 1


def test_ocr_empty_output_has_no_fabricated_word_or_absence_claim():
    result = parse_tesseract_tsv(_payload(), width=100, height=100)
    assert result["text"] == ""
    assert result["evidence"] == []
    assert result["coverage"] == {"selected_image": 1, "document_complete": "not_established"}


@pytest.mark.parametrize("bad", [b"", HEADER.replace("conf", "confidence").encode(), (HEADER + "\textra").encode(), b"\xef\xbb\xbf" + HEADER.encode()])
def test_ocr_exact_header_is_required(bad):
    with pytest.raises(ValueError):
        parse_tesseract_tsv(bad, width=100, height=100)


@pytest.mark.parametrize("field,value", [
    ("page", 2), ("level", 0), ("level", 6), ("block", 0),
    ("paragraph", 0), ("line", 0), ("word", 0),
    ("left", -1), ("top", -1), ("width", -1), ("height", -1),
    ("left", 90), ("top", 95), ("width", 0), ("height", 0),
    ("score", "nan"), ("score", "inf"), ("score", "-1"),
    ("score", "100.01"), ("score", "1_0"), ("score", " 90"),
    ("word", "True"), ("word", "1.0"), ("word", "+1"),
])
def test_invalid_word_fields_reject_the_entire_response(field, value):
    with pytest.raises(ValueError):
        parse_tesseract_tsv(_payload(_row(**{field: value})), width=100, height=100)


@pytest.mark.parametrize("text", [" robot", "robot ", "robot\rname", "robot\tname", "robot\nname"])
def test_ocr_word_controls_or_ambiguous_columns_are_refused(text):
    with pytest.raises(ValueError):
        parse_tesseract_tsv(_payload(_row(text)), width=100, height=100)


@pytest.mark.parametrize("change", ["duplicate", "reversed_lines", "reversed_blocks"])
def test_ocr_never_silently_reorders_or_duplicates_words(change):
    if change == "duplicate":
        rows = [_row("a"), _row("b")]
    elif change == "reversed_lines":
        rows = [_row("a", line=2), _row("b", line=1)]
    else:
        rows = [_row("a", block=2), _row("b", block=1)]
    with pytest.raises(ValueError, match="reading order"):
        parse_tesseract_tsv(_payload(*rows), width=100, height=100)


def test_crlf_native_rows_and_empty_word_rows_are_supported():
    payload = _payload(_row("", score="0"), _row("robot", word=2)).replace(b"\n", b"\r\n")
    assert parse_tesseract_tsv(payload, width=100, height=100)["text"] == "robot"


def test_late_invalid_row_does_not_return_partially_accepted_text():
    with pytest.raises(ValueError):
        parse_tesseract_tsv(_payload(_row("valid"), _row("invalid", word=2, score="nan")), width=100, height=100)


def test_tsv_row_budget_is_enforced_without_reconstructed_data():
    row = "1\t1\t0\t0\t0\t0\t0\t0\t1\t1\t-1\t\n"
    payload = HEADER.encode() + b"\n" + row.encode() * 10_001
    assert len(payload) <= 256 * 1024
    with pytest.raises(ValueError, match="row budget"):
        parse_tesseract_tsv(payload, width=1, height=1)


def test_ocr_exact_word_budget_is_accepted():
    rows = [_row("w", word=index, left=0, top=0, width=1, height=1, score="0") for index in range(1, 513)]
    result = parse_tesseract_tsv(_payload(*rows), width=2, height=2)
    assert len(result["evidence"]) == 512
    assert result["text"].split() == ["w"] * 512


def test_ocr_word_budget_overflow_is_refused_instead_of_truncated():
    rows = [_row("w", word=index, left=0, top=0, width=1, height=1, score="0") for index in range(1, 514)]
    with pytest.raises(ValueError, match="512-word"):
        parse_tesseract_tsv(_payload(*rows), width=2, height=2)


@pytest.mark.parametrize("dimension", [True, False, 0, -1, 1.0, "100", None])
def test_image_dimensions_are_strict_positive_integers(dimension):
    with pytest.raises(ValueError):
        parse_tesseract_tsv(_payload(_row()), width=dimension, height=100)
    with pytest.raises(ValueError):
        parse_tesseract_tsv(_payload(_row()), width=100, height=dimension)


@pytest.mark.parametrize("payload", [bytearray(b"abc"), "text", None, b"\xff", b"\x00", b"\x1b", "a\u0085b".encode(), b"x" * (256 * 1024 + 1)])
def test_payload_types_encoding_controls_and_byte_budget(payload):
    with pytest.raises(ValueError):
        parse_pdf_text(payload)
    with pytest.raises(ValueError):
        parse_tesseract_tsv(payload, width=100, height=100)


def test_pdf_text_and_page_spans_retain_native_unicode_and_separators():
    original = "  été\n\frobot\r\n\f"
    result = parse_pdf_text(original.encode("utf-8"), max_pages=2)
    assert result["text"] == original
    assert [item["char_range"] for item in result["evidence"]] == [[0, 6], [7, 14]]
    assert [original[slice(*item["char_range"])] for item in result["evidence"]] == ["  été\n", "robot\r\n"]
    assert result["coverage"] == {"pages_requested": [1, 2], "pages_returned": 2, "document_complete": "not_established"}


@pytest.mark.parametrize("payload,pages,spans", [
    (b"", 0, []), (b"\f", 1, [[0, 0]]), (b"\f\f", 2, [[0, 0], [1, 1]]),
    (b"text", 1, [[0, 4]]), (b"text\f", 1, [[0, 4]]),
    (b"text\f \r\n", 1, [[0, 4]]), (b"\n", 1, [[0, 1]]),
])
def test_pdf_empty_pages_and_terminal_breaks_do_not_invent_a_page(payload, pages, spans):
    result = parse_pdf_text(payload)
    assert result["text"] == payload.decode("utf-8")
    assert result["coverage"]["pages_returned"] == pages
    assert [item["char_range"] for item in result["evidence"]] == spans


def test_pdf_more_pages_than_requested_are_refused_without_partial_text():
    with pytest.raises(ValueError, match="more pages"):
        parse_pdf_text(b"one\ftwo\fthree\f", max_pages=2)


@pytest.mark.parametrize("pages", [True, False, 0, 9, -1, 1.0, "3", None])
def test_pdf_page_budget_is_strict(pages):
    with pytest.raises(ValueError):
        parse_pdf_text(b"text", max_pages=pages)


def test_source_like_recognized_text_is_never_executed(tmp_path):
    sentinel = tmp_path / "must-not-exist"
    source = f"open({str(sentinel)!r},'w').write('executed')"
    result = parse_pdf_text(source.encode("utf-8"))
    assert result["text"] == source
    result = parse_tesseract_tsv(_payload(_row(source, width=100)), width=200, height=100)
    assert result["text"] == source
    assert not sentinel.exists()


def test_parser_results_do_not_share_mutable_state():
    payload = _payload(_row())
    first = parse_tesseract_tsv(payload, width=100, height=100)
    original = deepcopy(first)
    first["evidence"][0]["bbox"][0] = 99
    first["limitations"].clear()
    assert parse_tesseract_tsv(payload, width=100, height=100) == original
    pdf = parse_pdf_text(b"text\f")
    pdf["coverage"]["pages_requested"][0] = 8
    assert parse_pdf_text(b"text\f")["coverage"]["pages_requested"] == [1, 3]
