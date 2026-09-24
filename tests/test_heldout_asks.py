from tiberium_ai.heldout_asks import measure_new_ask_coverage


def _revision(name, rows):
    return {
        "revision_id": name,
        "prompts": [{"text": text, "count": count} for text, count in rows],
    }


def test_heldout_is_content_based_and_keeps_repeats_out():
    reference = _revision("old", [("extract columns", 2)])
    current = _revision(
        "new",
        [
            ("extract columns", 100),
            ("extract the rows", 2),
            ("continuer", 7),
        ],
    )
    result = measure_new_ask_coverage(reference, current)
    assert result.new_distinct == 2
    assert result.new_volume == 9
    assert result.ask_distinct == 1
    assert result.ask_volume == 2
    assert result.verdict == "coverage_threshold_met"
    record = result.to_record()
    assert "extract the rows" not in str(record)
    assert record["claim"] == "coverage_only"


def test_no_new_text_cannot_prove_generalization():
    old = _revision("old", [("extract the rows", 1)])
    current = _revision("same", [("extract the rows", 50)])
    result = measure_new_ask_coverage(old, current)
    assert result.verdict == "empty_heldout"
    assert result.reports == ()
    assert result.ask_volume == 0
