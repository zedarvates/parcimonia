from copy import deepcopy
from hashlib import sha256

import pytest

from tiberium_ai.context_provenance import (
    attach_context_provenance, corpus_match_text, propose_paraphrase_pairs, recover_context_provenance,
)
from tiberium_ai.context_review import build_context_review_pack


def pack():
    return build_context_review_pack([{"text": "extraire les colonnes du fichier", "sources": ["sessions"]},
        {"text": "vérifier la cohérence du résultat", "sources": ["sessions"]},
        {"text": "reformater le document", "sources": ["sessions"]}], corpus_revision="revision")


def occurrence(text, thread="thread-1", ordinal=1, stamp=100):
    return {"thread_id": thread, "timestamp_ms": stamp, "source_kind": "sqlite_user_message",
        "locator": {"turn_id": "turn-1", "item_id": f"u-{ordinal}", "rollout_ordinal": ordinal},
        "item": {"type": "userMessage", "content": [{"type": "text", "text": text}]}}


def test_exact_corpus_transform_matches_harness_wrapped_inputs_without_labels():
    data = pack()
    wrapped = "<environment_context><cwd>C:/fixture</cwd></environment_context> ## My request: EXTRAIRE les colonnes du fichier"
    recovery = recover_context_provenance(data, [occurrence(wrapped)], cutoff_ms=200)
    assert recovery["recovered_cases"] == 1 and recovery["occurrences"] == 1
    found = next(values for values in recovery["matches"].values() if values)[0]
    assert found["recorded_input"]["cwd"] == "C:/fixture"
    enriched = attach_context_provenance(data, recovery)
    assert all(all(value is None for value in case["labels"].values()) for case in enriched["cases"])
    assert all(case["context_snapshot"] is None and not case["group_reviewed"] for case in enriched["cases"])


def test_future_unknown_timestamp_and_non_user_items_cannot_establish_old_provenance():
    data = pack()
    sources = [occurrence("extraire les colonnes du fichier", stamp=201),
               occurrence("extraire les colonnes du fichier", stamp=0)]
    non_user = occurrence("extraire les colonnes du fichier")
    non_user["item"]["type"] = "agentMessage"
    sources.append(non_user)
    recovery = recover_context_provenance(data, sources, cutoff_ms=200)
    assert recovery["recovered_cases"] == 0
    assert recovery["counters"]["outside_corpus_period"] == 1
    assert recovery["counters"]["unknown_timestamp"] == 1
    assert recovery["counters"]["malformed_records"] == 1


def test_prefix_and_similarity_are_not_exact_matches():
    data = pack()
    recovery = recover_context_provenance(data, [occurrence("extraire les colonnes du fichier puis les comparer"),
        occurrence("récupérer les colonnes du fichier")], cutoff_ms=200)
    assert recovery["recovered_cases"] == 0
    assert corpus_match_text(occurrence("x" * 1201)["item"]) is None


def test_all_occurrences_and_transitive_shared_threads_are_kept_in_one_component():
    data = pack()
    cases = data["cases"]
    sources = [occurrence(cases[0]["text"], "t1", 1), occurrence(cases[0]["text"], "t2", 1),
        occurrence(cases[1]["text"], "t2", 2), occurrence(cases[1]["text"], "t3", 1),
        occurrence(cases[2]["text"], "t3", 2)]
    recovery = recover_context_provenance(data, sources + [sources[0]], cutoff_ms=200)
    assert recovery["occurrences"] == 5 and recovery["distinct_threads"] == 3
    enriched = attach_context_provenance(data, recovery)
    assert enriched["source_component_count"] == 1
    assert len({case["source_group"] for case in enriched["cases"]}) == 1
    assert enriched["parent_pack_id"] == data["pack_id"] and enriched["pack_id"] != data["pack_id"]


def test_identity_mismatch_and_wrong_pack_are_rejected():
    data = pack()
    recovery = recover_context_provenance(data, [], cutoff_ms=200)
    wrong = deepcopy(recovery)
    wrong["parent_pack_id"] = "another-pack"
    with pytest.raises(ValueError, match="different pack"):
        attach_context_provenance(data, wrong)
    data["cases"][0]["text"] = "changed"
    with pytest.raises(ValueError, match="identity"):
        recover_context_provenance(data, [], cutoff_ms=200)


def test_lexical_pairs_are_only_unreviewed_proposals():
    data = build_context_review_pack([{"text": "extraire colonnes document tableau CSV vérifier", "sources": []},
        {"text": "extraire colonnes document tableau CSV comparer", "sources": []}], corpus_revision="fixture")
    before = deepcopy(data)
    pairs = propose_paraphrase_pairs(data)
    assert len(pairs) == 1 and pairs[0]["status"] == "unreviewed"
    assert data == before and all(case["paraphrase_group"] is None for case in data["cases"])
