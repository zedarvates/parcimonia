from hashlib import sha256
import json
import subprocess

import pytest

from tiberium_ai import repo_evidence as evidence


def test_retrieves_sources_without_inventory_and_cites_exact_lines():
    files = {
        "other/deep/resume_index.py": b"\ndef resume_index(journal):\n    return journal.resume()\n",
        "qa/resume_index.test.ts": b"test('resume index from journal', () => {});\n",
        "manual/resume_index.md": b"# Resume index from the journal\nVerify the original journal.\n",
        "src/unrelated.py": b"def compute_price(): pass\n",
    }
    result = evidence.select_repository_evidence("Resume index from journal", files)
    assert result["status"] == "review_required" and not result["missing"]
    assert [result["roles"][role][0]["path"] for role in evidence.ROLES] == list(files)[:3]
    for lane in result["roles"].values():
        for item in lane:
            raw = files[item["path"]]
            assert item["sha256"] == sha256(raw).hexdigest()
            for excerpt in item["excerpts"]:
                assert excerpt["text"] == "\n".join(raw.decode().splitlines()[excerpt["start"]-1:excerpt["end"]])
    assert result["model_calls"] == 0 and not result["proof_verified"]
    assert not result["auto_act_allowed"]


def test_reports_missing_category_and_specific_missing_need():
    result = evidence.select_repository_evidence(
        "Retry failed reads; record all attempts", {"src/retry.py": b"def retry_failed_reads(): pass\n"},
        requirements={"code": ["record durable journal"], "tests": ["retry failed reads"]})
    reasons = {(row["role"], row["reason"]) for row in result["missing"]}
    assert ("docs", "no_sufficient_lexical_excerpt") in reasons
    assert ("tests", "requirement_not_located") in reasons
    assert ("code", "requirement_not_located") in reasons
    assert (None, "goal_part_not_located") in reasons
    assert result["status"] == "gaps_detected"


def test_does_not_claim_empty_or_path_only_matches_as_evidence():
    result = evidence.select_repository_evidence(
        "unique signature", {"docs/unique_signature.md": b"Empty.", "unique_signature.py": b""})
    assert not any(result["roles"].values())
    assert {r["role"] for r in result["missing"]} == {None, "code", "tests", "docs"}


def test_unreadable_content_and_capped_reads_are_disclosed(monkeypatch):
    monkeypatch.setattr(evidence, "MAX_FILE_BYTES", 18)
    result = evidence.select_repository_evidence(
        "retry journal", {"retry.py": b"retry journal",
                          "docs/invalid.md": b"\xff", "src/large.py": b"retry journal" * 10})
    assert result["scope"]["skipped"] == {"not_utf8": 1, "budget": 1}
    assert {"role": None, "reason": "repository_scope_incomplete"} in result["missing"]


def test_repository_cli_scans_tracked_current_files_only(tmp_path, capsys):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "outside_inventory").mkdir()
    source = tmp_path / "outside_inventory" / "journal.py"
    source.write_text("def old(): pass\n", encoding="utf-8")
    (tmp_path / "secrets.json").write_text('{"retry": "journal"}', encoding="utf-8")
    git("add", ".")
    source.write_text("def retry_journal(): pass\n", encoding="utf-8")
    (tmp_path / "not_tracked.py").write_text("def retry_journal(): pass\n", encoding="utf-8")
    evidence.main(["--root", str(tmp_path), "--goal", "retry journal", "--format", "json"])
    result = json.loads(capsys.readouterr().out)
    assert result["scope"]["indexed_files"] == 1
    assert result["roles"]["code"][0]["path"] == "outside_inventory/journal.py"
    assert result["roles"]["code"][0]["sha256"] == sha256(source.read_bytes()).hexdigest()
    assert not result["roles"]["tests"] and not result["roles"]["docs"]


def test_regular_reader_rejects_link_and_escape(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-external.py"
    outside.write_text("retry journal")
    try:
        try:
            (tmp_path / "link.py").symlink_to(outside)
        except OSError:
            pytest.skip("local OS does not allow creating a symlink")
        assert evidence._read_regular(tmp_path, "link.py") is None
        result = evidence.select_repository_evidence("retry journal", {"../external.py": outside.read_bytes()})
        assert not any(result["roles"].values())
    finally:
        outside.unlink()


def test_second_pass_preserves_source_titles_and_recovers_another_section_within_budget():
    text = (
        "Introductory lines without useful keywords.\n"
        "A second broad introduction before the title.\n"
        "## Contract\n"
        "The durable journal records retries.\n"
        "Long surrounding prose that adds nothing relevant to this request.\n"
        "\n```python\n"
        "def journal():\n"
        "    return 'durable journal'\n"
        "```\n\n"
        "## Failure recovery\n"
        "Resume from the durable journal.\n"
    )
    lines = text.splitlines()
    first = [{"start": 1, "end": 5, "text": "\n".join(lines[:5]),
              "matches": ["durable", "journal", "retries"]}]
    wanted = set(evidence._tokens("durable journal retries resume"))
    result = evidence._refine_slices(text, first, wanted, dict.fromkeys(wanted, 1),
                                     ["durable journal retries", "resume"], role="docs")
    assert [lines[e["start"] - 1] for e in result] == ["## Contract", "## Failure recovery"]
    assert "resume" in result[1]["matches"]
    assert sum(len(e["text"].encode()) for e in result) <= len(first[0]["text"].encode())
    assert sum(e["end"] - e["start"] + 1 for e in result) <= 5
    assert all(e["text"] == "\n".join(lines[e["start"] - 1:e["end"]]) for e in result)


def test_phrase_requires_one_passage_not_words_collected_across_files():
    sources = {
        "tests/test_archive.py": b"def test_archive():\n    assert archived_journal\n",
        "tests/test_reject.py": b"def test_reject():\n    assert rejected_duplicate\n",
    }
    out = evidence.select_repository_evidence("Verify archived journal", sources,
        required_roles=("tests",), requirements={"tests": ["archived journal rejected duplicate"]})
    need = next(row for row in out["requirement_links"] if row["kind"] == "explicit")
    assert need["status"] == "insufficient" and len(need["missing_terms"]) == 2
    assert out["status"] == "gaps_detected"
    assert any(g["requirement"] == need["id"] for g in out["missing"])
    cite = need["citations"][0]
    assert cite["sha256"] == sha256(sources[cite["path"]]).hexdigest()


def test_exact_symbol_finds_declaration_and_ignores_mentions():
    target = "recover_transaction_receipt"
    code = ("description = '''\ndef recover_transaction_receipt():\n    pass\n'''\n"
            "# def recover_transaction_receipt():\n"
            "async def recover_transaction_receipt():\n    return 'receipt'\n")
    raw = code.encode()
    out = evidence.select_repository_evidence("Recover transaction receipt",
        {"src/worker.py": raw, "src/demo.py": b"recover_transaction_receipt = 'example'\n"},
        limit=1, required_roles=("code",), requirements={"code": [f"@{target}"]})
    link = next(row for row in out["requirement_links"] if row["kind"] == "symbol")
    assert link["status"] == "linked_candidate"
    assert link["citations"] == [{"role": "code", "path": "src/worker.py",
        "start": 6, "end": 6, "sha256": sha256(raw).hexdigest(),
        "text": f"async def {target}():"}]
    assert not out["proof_verified"]


def test_exact_symbol_duplicate_is_ambiguous_even_at_one_file_budget():
    raw = b"def test_recover_receipt():\n    assert recovered_receipt\n"
    out = evidence.select_repository_evidence("Recover receipt",
        {"tests/test_a.py": raw, "tests/test_b.py": raw},
        limit=1, required_roles=("tests",), requirements={"tests": ["@test_recover_receipt"]})
    link = next(row for row in out["requirement_links"] if row["kind"] == "symbol")
    assert link["status"] == "ambiguous"
    assert len(link["citations"]) == 2
    assert len(out["roles"]["tests"]) == 1
    assert any(g["reason"] == "requirement_ambiguous" for g in out["missing"])


def test_exact_symbol_with_unparseable_candidate_reports_incomplete_scope():
    out = evidence.select_repository_evidence("Recover receipt",
        {"src/broken.py": b"def recover_receipt(:\n",
         "src/worker.py": b"def recover_receipt():\n    return receipt\n"},
        required_roles=("code",), requirements={"code": ["@recover_receipt"]})
    assert any(g["reason"] == "requirement_scope_incomplete" for g in out["missing"])
    assert not out["proof_verified"]


def test_follows_imported_call_and_markdown_link_with_unrelated_vocabulary():
    sources = {
        "src/demo/store.py": b"def put():\n    return 'Archive canonical transaction receipts'\n",
        "tests/test_a.py": b"import demo.store as storage\ndef test_ok():\n    assert storage.put()\n",
        "docs/operator.md": b"# Operator\n[Writer](../src/demo/store.py)\n",
    }
    out = evidence.select_repository_evidence("Archive canonical transaction receipts", sources,
        limit=3, requirements={"tests": ["duplicate audit"]})
    assert {link["kind"] for link in out["source_relations"]} == {"test_calls_code", "doc_references_code"}
    assert any(g["reason"] == "requirement_not_located" for g in out["missing"])
    assert not any(g["reason"] == "no_sufficient_lexical_excerpt" for g in out["missing"])
    assert sum(map(len, out["roles"].values())) == 3
    for link in out["source_relations"]:
        ref = link["source"]
        assert ref["sha256"] == sha256(sources[ref["path"]]).hexdigest()
        f = next(f for f in out["roles"][ref["role"]] if f["path"] == ref["path"])
        assert any(e["start"] <= ref["start"] <= e["end"] for e in f["excerpts"])
    assert not out["proof_verified"]


def test_does_not_link_shadowed_aliases_or_links_in_fenced_examples():
    sources = {
        "src/demo/store.py": b"def put():\n    return 'Archive canonical transaction receipts'\n",
        "tests/test_a.py": b"import demo.store as storage\ndef test_ok(storage):\n    assert storage.put()\n",
        "tests/test_b.py": b"from demo.store import put\ndef test_ok():\n    put = lambda: True\n    assert put()\n",
        "docs/operator.md": b"```md\n[Writer](../src/demo/store.py)\n```\n",
    }
    out = evidence.select_repository_evidence("Archive canonical transaction receipts", sources)
    assert not out["source_relations"]
    assert {g["role"] for g in out["missing"]} == {"tests", "docs"}


def test_unqualified_ambiguous_markdown_symbol_needs_a_qualified_reference():
    sources = {
        "src/demo/store.py": b"def put():\n    return 'Archive canonical transaction receipts'\n",
        "src/demo/other.py": b"def put():\n    return None\n",
        "docs/operator.md": b"Call `put` once.\n",
    }
    out = evidence.select_repository_evidence("Archive canonical transaction receipts", sources)
    assert not out["source_relations"]
    sources["docs/operator.md"] = b"Call `demo.store.put` once.\n"
    out = evidence.select_repository_evidence("Archive canonical transaction receipts", sources)
    assert [link["kind"] for link in out["source_relations"]] == ["doc_references_code"]


def test_recovers_helper_call_and_target_declaration_with_verifiable_lines():
    source = ("def put():\n" + "    # unrelated context\n" * 18
              + "    return 'Archive canonical transaction receipts'\n").encode()
    test = b"import demo.store as storage\ndef bridge():\n    return storage.put()\ndef test_ok():\n    assert bridge()\n"
    files = {"src/demo/store.py": source, "tests/test_a.py": test}
    first = evidence.select_repository_evidence("Archive canonical transaction receipts", files,
                                                required_roles=("code", "tests"))
    assert not first["source_relations"]
    out = evidence.select_repository_evidence("Archive canonical transaction receipts", files,
        required_roles=("code", "tests"), follow_paths=True)
    link = out["source_relations"][0]
    assert link["kind"] == "test_calls_via_helper"
    assert link["via"]["helper"] == "bridge" and link["via"]["start"] == 5
    assert link["source"]["start"] == 3 and link["declaration"]["start"] == 1
    assert any(e["start"] <= 1 <= e["end"] for e in out["roles"]["code"][0]["excerpts"])
    assert not out["proof_verified"]


def test_does_not_follow_shadowed_helpers_or_two_local_hops():
    test = (b"from demo.store import put\ndef bridge():\n    return put()\n"
            b"def other():\n    return bridge()\n"
            b"def test_two():\n    assert other()\n"
            b"def test_shadowed(bridge):\n    assert bridge()\n")
    out = evidence.select_repository_evidence("Archive canonical transaction receipts",
        {"src/demo/store.py": b"def put():\n    return 'Archive canonical transaction receipts'\n",
         "tests/test_a.py": test}, required_roles=("code", "tests"), follow_paths=True)
    assert not out["source_relations"]
    assert any(g["role"] == "tests" for g in out["missing"])


def test_related_doc_cites_enclosing_heading_even_when_the_link_is_farther_down():
    doc = ("# Operator\n" + "General instructions.\n" * 7 + "[Writer](../src/demo/store.py)\n").encode()
    out = evidence.select_repository_evidence("Archive canonical transaction receipts",
        {"src/demo/store.py": b"def put():\n    return 'Archive canonical transaction receipts'\n",
         "docs/ops.md": doc}, required_roles=("code", "docs"), follow_paths=True)
    edge = out["source_relations"][0]
    assert edge["section"]["start"] == 1 and edge["source"]["start"] == 9
    assert any(e["text"] == "# Operator" for e in out["roles"]["docs"][0]["excerpts"])
