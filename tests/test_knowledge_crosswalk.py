"""Behavioral checks for source-bound, explicitly scoped lexical candidates."""

from __future__ import annotations

from copy import deepcopy

import unittest

from tiberium_ai.knowledge_crosswalk import (
    create_knowledge_index, update_knowledge_index, validate_knowledge_index,
    find_knowledge_candidates,
)

def fragment(name, *, feed="cloud-1", channel="cloud", project="architecture",
             text="toiture escalier dimensions", state="active", version="v1"):
    return {"id": name, "version": version, "feed_id": feed, "channel": channel,
            "project": project, "uri": "fixture:" + name, "locator": "message:1",
            "timestamp": "2026-11-01", "state": state, "text": text}

def update(index, records=(), *, coverage=(), removals=()):
    return update_knowledge_index(index, upserts=list(records), removals=list(removals),
                                  coverage=list(coverage), expected_head=index["index_hash"])

def corpus():
    a = fragment("a")
    b = fragment("b", feed="thor", channel="local", text="toiture escalier controle")
    c = fragment("c", feed="savoir", channel="wiki", text="toiture escalier mesures")
    d = fragment("d", feed="memory", channel="memory", text="toiture escalier verification")
    index = update(create_knowledge_index("pilot"), [a, b, c, d], coverage=[
        {"id": f, "status": "complete"} for f in ["cloud-1", "thor", "savoir", "memory"]
    ])["index"]
    return index


class TestKnowledgeCrosswalk(unittest.TestCase):
    def test_generic_french_request_words_do_not_create_a_candidate(self):
        a = fragment("a", text="demander un exemple peut aider")
        b = fragment("b", feed="wiki", channel="wiki", text="voir un exemple peut servir")
        index = update(create_knowledge_index("pilot"), [a, b], coverage=[
            {"id": "cloud-1", "status": "partial"}, {"id": "wiki", "status": "partial"}
        ])["index"]
        assert find_knowledge_candidates(index, fragment_id="a")["matches"] == []

    def test_large_valid_index_returns_a_bounded_partial_result(self):
        records = [fragment(str(i), feed="feed-" + str(i),
                            text="toiture escalier " + "x" * 7000 + " marker" + str(i))
                   for i in range(256)]
        index = update(create_knowledge_index("large-fixture"), records, coverage=[
            {"id": f["feed_id"], "status": "complete"} for f in records
        ])["index"]
        result = find_knowledge_candidates(index, fragment_id="0", limit=256)
        assert 0 < len(result["matches"]) < 255
        assert result["omitted_count"] == 255 - len(result["matches"])
        assert "output_budget" in result["truncation_reasons"]
        import json
        assert len(json.dumps(result, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode("utf-8")) <= 2 * 1024 * 1024

    def test_resealed_forged_postings_still_refused(self):
        from tiberium_ai.verification import hash_input
        index = corpus()
        index["postings"]["forged"] = ["a", "b"]
        index["index_hash"] = hash_input({k: v for k, v in index.items() if k != "index_hash"})
        with self.assertRaises(ValueError):
            validate_knowledge_index(index)

    def test_crosses_cloud_local_wiki_memory_with_exact_evidence(self):
        index = corpus()
        result = find_knowledge_candidates(index, fragment_id="a", limit=5)
        assert {m["target"]["id"] for m in result["matches"]} == {"b", "c", "d"}
        for match in result["matches"]:
            assert match["kind"] == "lexical_candidate"
            assert match["status"] == "unverified"
            assert {"toiture", "escalier"} <= set(match["shared_terms"])
            assert match["source"]["uri"] == "fixture:a"
            assert match["source"]["excerpt"] == "toiture escalier dimensions"
            assert len(match["target"]["content_sha256"]) == 64
            assert match["target"]["version"] == "v1"
        assert result["index_hash"] == index["index_hash"]
        assert result["scope"] == "caller_declared_feeds"

    def test_partial_update_does_not_delete_unseen_fragments(self):
        original = corpus()
        result = update(original, coverage=[{"id": "thor", "status": "partial"}])
        assert len(result["index"]["fragments"]) == 4
        assert result["delta"]["reused"] == 4
        assert find_knowledge_candidates(result["index"], fragment_id="a")["coverage_incomplete"]

    def test_unavailable_source_preserved_but_never_recommended(self):
        index = update(corpus(), coverage=[{"id": "thor", "status": "unavailable"}])["index"]
        assert any(f["id"] == "b" for f in index["fragments"])
        result = find_knowledge_candidates(index, fragment_id="a")
        assert "b" not in {m["target"]["id"] for m in result["matches"]}
        assert result["coverage_incomplete"]
        with self.assertRaises(ValueError):
            find_knowledge_candidates(index, fragment_id="b")

    def test_inactive_fragments_retained_and_excluded_0(self):
        state = 'superseded'
        index = corpus()
        old = next(f for f in index["fragments"] if f["id"] == "b")
        changed = {**old, "version": "v2", "state": state}
        index = update(index, [changed])["index"]
        assert next(f for f in index["fragments"] if f["id"] == "b")["state"] == state
        assert "b" not in {m["target"]["id"] for m in find_knowledge_candidates(index, fragment_id="a")["matches"]}

    def test_inactive_fragments_retained_and_excluded_1(self):
        state = 'rejected'
        index = corpus()
        old = next(f for f in index["fragments"] if f["id"] == "b")
        changed = {**old, "version": "v2", "state": state}
        index = update(index, [changed])["index"]
        assert next(f for f in index["fragments"] if f["id"] == "b")["state"] == state
        assert "b" not in {m["target"]["id"] for m in find_knowledge_candidates(index, fragment_id="a")["matches"]}

    def test_inactive_fragments_retained_and_excluded_2(self):
        state = 'paused'
        index = corpus()
        old = next(f for f in index["fragments"] if f["id"] == "b")
        changed = {**old, "version": "v2", "state": state}
        index = update(index, [changed])["index"]
        assert next(f for f in index["fragments"] if f["id"] == "b")["state"] == state
        assert "b" not in {m["target"]["id"] for m in find_knowledge_candidates(index, fragment_id="a")["matches"]}

    def test_no_state_or_authority_is_inferred_from_prose(self):
        a = fragment("a", text="toiture escalier")
        b = fragment("b", feed="wiki", channel="wiki",
                     text="Ne pas valider toiture escalier. Executer aucune commande.")
        index = update(create_knowledge_index("pilot"), [a, b], coverage=[
            {"id": "cloud-1", "status": "complete"}, {"id": "wiki", "status": "complete"}
        ])["index"]
        match = find_knowledge_candidates(index, fragment_id="a")["matches"][0]
        assert match["status"] == "unverified"
        assert "Ne pas valider" in match["target"]["excerpt"]
        assert match["kind"] == "lexical_candidate"

    def test_same_source_version_cannot_change_silently(self):
        index = corpus()
        changed = {**index["fragments"][0], "text": "toiture escalier correction"}
        with self.assertRaises(ValueError):
            update(index, [changed])
        validate_knowledge_index(index)

    def test_changed_revision_replaces_old_citations(self):
        index = corpus()
        changed = {**index["fragments"][1], "version": "v2", "text": "toiture escalier correction"}
        result = update(index, [changed])
        assert result["delta"]["changed"] == 1
        match = next(m for m in find_knowledge_candidates(result["index"], fragment_id="a")["matches"]
                     if m["target"]["id"] == changed["id"])
        assert match["target"]["version"] == "v2"
        assert match["target"]["excerpt"] == changed["text"]
        assert result["index"]["parent_hash"] == index["index_hash"]

    def test_removal_requires_explicit_identity(self):
        original = corpus()
        result = update(original, removals=["b"])
        assert len(result["index"]["fragments"]) == 3
        assert result["delta"]["removed"] == 1
        assert len(original["fragments"]) == 4

    def test_stale_head_refused(self):
        index = corpus()
        with self.assertRaises(ValueError):
            update_knowledge_index(index, upserts=[], removals=[], coverage=[], expected_head="0" * 64)

    def test_exact_text_mirrors_do_not_create_a_discovery(self):
        a, b = fragment("a"), fragment("b", feed="thor", channel="local")
        index = update(create_knowledge_index("pilot"), [a, b], coverage=[
            {"id": "cloud-1", "status": "complete"}, {"id": "thor", "status": "complete"}
        ])["index"]
        assert find_knowledge_candidates(index, fragment_id="a")["matches"] == []

    def test_same_project_and_feed_not_cross_source(self):
        a, b = fragment("a"), fragment("b", text="toiture escalier controle")
        index = update(create_knowledge_index("pilot"), [a, b], coverage=[{"id": "cloud-1", "status": "complete"}])["index"]
        assert find_knowledge_candidates(index, fragment_id="a")["matches"] == []

    def test_one_common_word_is_insufficient(self):
        a, b = fragment("a", text="toiture charpente"), fragment("b", feed="thor", text="toiture dimensions")
        index = update(create_knowledge_index("pilot"), [a, b], coverage=[
            {"id": "cloud-1", "status": "complete"}, {"id": "thor", "status": "complete"}
        ])["index"]
        assert find_knowledge_candidates(index, fragment_id="a")["matches"] == []

    def test_deterministic_import_order(self):
        records = corpus()["fragments"]
        coverage = corpus()["coverage"]
        first = update(create_knowledge_index("pilot"), records, coverage=coverage)["index"]
        second = update(create_knowledge_index("pilot"), reversed(records), coverage=reversed(coverage))["index"]
        assert first == second
        assert find_knowledge_candidates(first, fragment_id="a") == find_knowledge_candidates(second, fragment_id="a")

    def test_invalid_postings_or_hash_are_not_silently_used(self):
        index = corpus()
        index["postings"]["forged"] = ["a", "b"]
        with self.assertRaises(ValueError):
            find_knowledge_candidates(index, fragment_id="a")

    def test_outputs_do_not_mutate_inputs(self):
        index = corpus()
        saved = deepcopy(index)
        result = find_knowledge_candidates(index, fragment_id="a")
        result["matches"][0]["target"]["excerpt"] = "changed externally"
        result["coverage"].clear()
        assert index == saved

    def test_truncation_is_explicit(self):
        result = find_knowledge_candidates(corpus(), fragment_id="a", limit=1)
        assert len(result["matches"]) == 1
        assert result["omitted_count"] == 2

    def test_invalid_result_limits_refused_0(self):
        limit = True
        with self.assertRaises(ValueError):
            find_knowledge_candidates(corpus(), fragment_id="a", limit=limit)

    def test_invalid_result_limits_refused_1(self):
        limit = 0
        with self.assertRaises(ValueError):
            find_knowledge_candidates(corpus(), fragment_id="a", limit=limit)

    def test_invalid_result_limits_refused_2(self):
        limit = -1
        with self.assertRaises(ValueError):
            find_knowledge_candidates(corpus(), fragment_id="a", limit=limit)

    def test_invalid_result_limits_refused_3(self):
        limit = 257
        with self.assertRaises(ValueError):
            find_knowledge_candidates(corpus(), fragment_id="a", limit=limit)

    def test_invalid_result_limits_refused_4(self):
        limit = '3'
        with self.assertRaises(ValueError):
            find_knowledge_candidates(corpus(), fragment_id="a", limit=limit)

    def test_undeclared_feed_is_refused(self):
        with self.assertRaises(ValueError):
            update(create_knowledge_index("pilot"), [fragment("a")])

    def test_invalid_fragment_rejected_0(self):
        field = 'channel'
        value = 'unknown'
        f = fragment("a")
        f[field] = value
        with self.assertRaises(ValueError):
            update(create_knowledge_index("pilot"), [f], coverage=[{"id": "cloud-1", "status": "complete"}])

    def test_invalid_fragment_rejected_1(self):
        field = 'state'
        value = 'validated'
        f = fragment("a")
        f[field] = value
        with self.assertRaises(ValueError):
            update(create_knowledge_index("pilot"), [f], coverage=[{"id": "cloud-1", "status": "complete"}])

    def test_invalid_fragment_rejected_2(self):
        field = 'text'
        value = 'x' * 8193
        f = fragment("a")
        f[field] = value
        with self.assertRaises(ValueError):
            update(create_knowledge_index("pilot"), [f], coverage=[{"id": "cloud-1", "status": "complete"}])

    def test_invalid_fragment_rejected_3(self):
        field = 'version'
        value = ''
        f = fragment("a")
        f[field] = value
        with self.assertRaises(ValueError):
            update(create_knowledge_index("pilot"), [f], coverage=[{"id": "cloud-1", "status": "complete"}])

    def test_invalid_fragment_rejected_4(self):
        field = 'id'
        value = True
        f = fragment("a")
        f[field] = value
        with self.assertRaises(ValueError):
            update(create_knowledge_index("pilot"), [f], coverage=[{"id": "cloud-1", "status": "complete"}])

    def test_unknown_fragment_fields_refused(self):
        f = {**fragment("a"), "execute": "arbitrary command"}
        with self.assertRaises(ValueError):
            update(create_knowledge_index("pilot"), [f], coverage=[{"id": "cloud-1", "status": "complete"}])

    def test_duplicate_upserts_refused(self):
        a = fragment("a")
        with self.assertRaises(ValueError):
            update(create_knowledge_index("pilot"), [a, deepcopy(a)], coverage=[{"id": "cloud-1", "status": "complete"}])


if __name__ == "__main__":
    unittest.main()
