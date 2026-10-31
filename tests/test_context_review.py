from copy import deepcopy

import pytest

from tiberium_ai.context_review import build_context_review_pack, freeze_context_review_split


def records():
    return [{"text": "extraire les colonnes de ce fichier", "sources": ["sessions"]},
            {"text": "reformater le rapport joint", "sources": ["archived_sessions"]},
            {"text": "vérifier la cohérence du document", "sources": ["sessions"]},
            {"text": "comparer les options selon leur coût", "sources": ["sessions"]}]


def test_pack_does_not_invent_labels_language_context_or_source_groups():
    pack = build_context_review_pack(records(), corpus_revision="revision-1", limit=3)
    assert pack["selected_count"] == 3 and pack["labelled_cases"] == 0
    assert not pack["independent_labels_established"] and pack["quality_metrics"] is None
    for case in pack["cases"]:
        assert all(value is None for value in case["labels"].values())
        assert case["context_snapshot"] is case["source_group"] is case["split"] is None
        assert case["language_review_required"] and case["labeler_id"] is None
    with pytest.raises(ValueError, match="source_group"):
        freeze_context_review_split(pack["cases"])


def test_selection_is_stable_to_input_order_and_content_addressed():
    first = build_context_review_pack(records(), corpus_revision="revision-1")
    second = build_context_review_pack(list(reversed(records())), corpus_revision="revision-1")
    assert first == second
    changed = build_context_review_pack(records(), corpus_revision="revision-2")
    assert first["pack_id"] != changed["pack_id"]


def test_exact_duplicates_merge_sources_without_adding_cases_or_labels():
    rows = records()
    duplicate = {"text": rows[0]["text"], "sources": ["archived_sessions"]}
    pack = build_context_review_pack(rows + [duplicate], corpus_revision="revision-1")
    assert pack["selected_count"] == len(rows)
    case = next(row for row in pack["cases"] if row["text"] == duplicate["text"])
    assert case["sources"] == ["archived_sessions", "sessions"]


def reviewed_cases():
    pack = build_context_review_pack(records(), corpus_revision="revision-1")
    return [{**case, "source_group": f"thread-{i}", "group_reviewed": True}
            for i, case in enumerate(pack["cases"])]


def test_grouped_split_is_disjoint_stable_and_keeps_paraphrases_together():
    cases = reviewed_cases()
    cases[0]["paraphrase_group"] = cases[1]["paraphrase_group"] = "same-intent"
    before = deepcopy(cases)
    split = freeze_context_review_split(cases)
    assert split == freeze_context_review_split(list(reversed(cases)))
    assert set(split["development"]).isdisjoint(split["heldout"])
    assert set(split["development"]) | set(split["heldout"]) == {row["case_id"] for row in cases}
    assert (cases[0]["case_id"] in split["development"]) == (cases[1]["case_id"] in split["development"])
    assert cases == before and not split["claim_allowed"]


def test_normalised_duplicates_and_shared_sources_form_transitive_groups():
    cases = reviewed_cases()
    cases[1]["text"] = "  " + cases[0]["text"].upper() + "  "
    cases[1]["source_group"] = cases[2]["source_group"] = "thread-shared"
    split = freeze_context_review_split(cases)
    first_three = [row["case_id"] in split["development"] for row in cases[:3]]
    assert len(set(first_three)) == 1


def test_single_source_cannot_be_presented_as_a_heldout_split():
    cases = reviewed_cases()
    for case in cases:
        case["source_group"] = "same-thread"
    with pytest.raises(ValueError, match="no source-disjoint"):
        freeze_context_review_split(cases)


@pytest.mark.parametrize("limit,seed", [(0, 1), (True, 1), (5, True)])
def test_invalid_selection_bounds_are_rejected(limit, seed):
    with pytest.raises(ValueError):
        build_context_review_pack(records(), corpus_revision="revision", limit=limit, seed=seed)


def test_group_review_must_be_an_explicit_boolean():
    cases = reviewed_cases()
    cases[0]["group_reviewed"] = "true"
    with pytest.raises(ValueError, match="reviewed"):
        freeze_context_review_split(cases)
