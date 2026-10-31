from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tiberium_ai.agent_recipes.core import fingerprint
from tiberium_ai.agent_recipes.source_review import (
    apply_source_review, build_source_review_pack, load_saved_source_manifest,
    source_comparison_readiness, source_review_template, validate_source_review_pack,
)
from tiberium_ai.agent_recipes.source_review_ui import render_source_review


def context():
    return {"id": "fixture-project", "revision": "1", "objective": "Review local evidence"}


def records(count=4):
    rows = []
    for i in range(count):
        text = f"uniquecontent{i}"
        digest = sha256(text.encode()).hexdigest()
        reference = f"fixture:source-{i}"
        rows.append({"source": {"id": fingerprint({"reference": reference, "sha256": digest}),
            "title": f"uniquetopic{i}", "text": text, "reference": reference},
            "provenance": {"snapshot_path": f"fixture-{i}.txt", "sha256": digest,
                "bytes": len(text.encode()), "captured_at": "2026-10-08T12:00:00Z",
                "reference": reference, "revision": "fixture-1", "lineage_id": f"lineage-{i}"}})
    return rows


def packet(count=4):
    return build_source_review_pack(records(count), context())


def completed_review(data):
    review = source_review_template(data)
    for annotation in review["annotations"].values():
        annotation.update(reviewer_id="fixture-reviewer", source_reviewed=True, language="en",
                          rationale="Authored contract test", complete=True)
        annotation["labels"].update(must_retain=True, attention="process")
        annotation["labels"]["relations"] = {key: "novel" for key in annotation["labels"]["relations"]}
    return review


def rehash(data):
    data["pack_id"] = fingerprint({key: data[key] for key in ("schema", "corpus_revision", "seed", "cases")})


def saved_manifest(tmp_path):
    root = tmp_path / "captures"
    directory = root / "Owner--model"
    directory.mkdir(parents=True)
    content = b"Actual saved content\r\n"
    (directory / "README.md").write_bytes(content)
    manifest = {"consulted_at_utc": "2026-10-07T12:00:00Z", "repositories": [{
        "repo": "Owner/model", "revision": "a" * 40, "files": [{
            "file": "README.md", "bytes": len(content), "sha256": sha256(content).hexdigest(),
            "url": "https://huggingface.co/Owner/model/resolve/" + "a" * 40 + "/README.md"}]}]}
    path = root / "sources-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest, directory / "README.md"


def test_saved_sources_are_hash_checked_and_full_text_preserved(tmp_path):
    path, _, snapshot = saved_manifest(tmp_path)
    result = load_saved_source_manifest(path)
    assert result["records"][0]["source"]["text"].encode() == snapshot.read_bytes()
    assert result["read_bytes"] == len(snapshot.read_bytes())
    assert not result["model_inference_executed"]
    assert result["manifest_sha256"] == sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("mutation", ["hash", "size", "url", "revision", "path", "timezone"])
def test_corrupted_saved_manifest_cannot_create_a_real_source(tmp_path, mutation):
    path, manifest, _ = saved_manifest(tmp_path)
    repo, entry = manifest["repositories"][0], manifest["repositories"][0]["files"][0]
    if mutation == "hash":
        entry["sha256"] = "0" * 64
    elif mutation == "size":
        entry["bytes"] = True
    elif mutation == "url":
        entry["url"] = "https://example.com/unpinned"
    elif mutation == "revision":
        repo["revision"] = "main"
    elif mutation == "path":
        entry["file"] = "../outside.txt"
    else:
        manifest["consulted_at_utc"] = "2026-10-07T12:00:00"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_saved_source_manifest(path)


@pytest.mark.parametrize("bounds", [{"max_file_bytes": 5}, {"max_total_bytes": 5}, {"max_files": 0}])
def test_read_bounds_are_enforced_without_truncation(tmp_path, bounds):
    path, _, snapshot = saved_manifest(tmp_path)
    original = snapshot.read_bytes()
    with pytest.raises(ValueError):
        load_saved_source_manifest(path, **bounds)
    assert snapshot.read_bytes() == original


def test_total_budget_exhaustion_never_reads_all_remaining_files(tmp_path):
    path, manifest, snapshot = saved_manifest(tmp_path)
    second = deepcopy(manifest["repositories"][0]["files"][0])
    second["file"] = "second.md"
    second["url"] = second["url"].replace("README.md", "second.md")
    snapshot.with_name("second.md").write_bytes(snapshot.read_bytes())
    manifest["repositories"][0]["files"].append(second)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="exhausted"):
        load_saved_source_manifest(path, max_total_bytes=len(snapshot.read_bytes()))


def test_build_is_order_stable_with_blank_labels_and_no_fake_context():
    rows = records()
    first = build_source_review_pack(rows, context())
    second = build_source_review_pack(list(reversed(rows)), context())
    assert first == second
    assert first["reviewed_cases"] == 0 and first["pending_cases"] == 4
    for case in first["cases"]:
        assert case["labels"]["must_retain"] is None and case["labels"]["attention"] is None
        assert all(value is None for value in case["labels"]["relations"].values())
        assert case["annotation"] is None and case["split"] is None
    assert source_comparison_readiness(first)["capture_ready"] is False
    assert source_comparison_readiness(first)["human_reviewed_cases"] == 0


def test_changed_text_cannot_be_presented_as_the_captured_source():
    rows = records()
    rows[0]["source"]["text"] += " fabricated evidence"
    with pytest.raises(ValueError, match="captured content"):
        build_source_review_pack(rows, context())


def test_context_revision_changes_case_and_packet_identity():
    original = build_source_review_pack(records(), context())
    changed = build_source_review_pack(records(), {**context(), "revision": "2"})
    assert original["pack_id"] != changed["pack_id"]
    assert {c["case_id"] for c in original["cases"]}.isdisjoint(c["case_id"] for c in changed["cases"])


def test_blank_review_cannot_freeze_or_create_labels():
    data = packet()
    result = apply_source_review(data, source_review_template(data))
    assert result["reviewed_cases"] == 0 and result["pending_cases"] == 4
    assert result["split_manifest"] is None
    with pytest.raises(ValueError, match="incomplete"):
        apply_source_review(data, source_review_template(data), require_complete=True)


def test_complete_review_freezes_disjoint_groups_with_final_hashes():
    data = packet()
    result = apply_source_review(data, completed_review(data), require_complete=True)
    validate_source_review_pack(result)
    split = result["split_manifest"]
    assert set(split["heldout"]).isdisjoint(split["development"])
    assert set(split["heldout"]) | set(split["development"]) == {case["case_id"] for case in result["cases"]}
    assert split["case_hashes"] == {case["case_id"]: fingerprint(case) for case in result["cases"]}
    assert split["case_hash_scope"] == "final_source_case/1"
    readiness = source_comparison_readiness(result, min_heldout=1)
    assert readiness["capture_ready"] is True and not readiness["independence_certified"]
    assert result["quality_metrics"] is None and result["cost_savings"] is None
    assert not result["claim_allowed"] and not result["auto_act_allowed"]


def test_shared_lineage_and_event_groups_stay_on_the_same_side():
    rows = records(6)
    rows[0]["provenance"]["lineage_id"] = rows[1]["provenance"]["lineage_id"] = "same-lineage"
    data = build_source_review_pack(rows, context())
    review = completed_review(data)
    selected = data["cases"][:2]
    for case in selected:
        review["annotations"][case["case_id"]]["event_group"] = "same-event"
    result = apply_source_review(data, review)
    lineage_sides = {case["split"] for case in result["cases"] if case["provenance"]["lineage_id"] == "same-lineage"}
    assert len(lineage_sides) == 1
    assert len({case["split"] for case in result["cases"] if case["case_id"] in {c["case_id"] for c in selected}}) == 1


def test_shared_candidate_sources_block_artificial_holdout():
    rows = records(3)
    for row in rows:
        row["source"]["title"] = "Shared topic"
    data = build_source_review_pack(rows, context())
    result = apply_source_review(data, completed_review(data))
    assert result["split_status"] == "no_source_disjoint_split"
    assert result["split_manifest"] is None
    assert "split_not_frozen" in source_comparison_readiness(result)["reason_codes"]


def test_single_real_source_cannot_form_a_heldout_split():
    data = packet(1)
    result = apply_source_review(data, completed_review(data))
    assert result["split_status"] == "no_source_disjoint_split"


@pytest.mark.parametrize("mutation", ["packet", "case-hash", "reviewer", "rationale", "source", "relations", "required-skip", "complete-type", "predictions"])
def test_forged_or_incomplete_annotation_is_rejected(mutation):
    data = packet()
    review = completed_review(data)
    annotation = next(iter(review["annotations"].values()))
    if mutation == "packet":
        review["packet_id"] = "foreign"
    elif mutation == "case-hash":
        annotation["case_hash"] = "wrong"
    elif mutation == "reviewer":
        annotation["reviewer_id"] = None
    elif mutation == "rationale":
        annotation["rationale"] = ""
    elif mutation == "source":
        annotation["source_reviewed"] = False
    elif mutation == "relations":
        annotation["labels"]["relations"]["foreign-candidate"] = "duplicate"
    elif mutation == "required-skip":
        annotation["labels"]["attention"] = "skip_candidate"
    elif mutation == "complete-type":
        annotation["complete"] = "true"
    else:
        annotation["model_answer"] = "duplicate"
    with pytest.raises(ValueError):
        apply_source_review(data, review)


def test_unknown_labels_remain_unknown_and_cannot_open_comparison():
    data = packet()
    review = completed_review(data)
    for annotation in review["annotations"].values():
        annotation["labels"].update(must_retain=None, attention="uncertain")
    result = apply_source_review(data, review)
    readiness = source_comparison_readiness(result, min_heldout=1)
    assert readiness["labelled_heldout_cases"] == 0 and not readiness["capture_ready"]


def test_modified_final_labels_cannot_be_rehashed_into_review_truth():
    data = packet()
    result = apply_source_review(data, completed_review(data))
    result["cases"][0]["labels"]["must_retain"] = False
    rehash(result)
    with pytest.raises(ValueError, match="differ"):
        source_comparison_readiness(result, min_heldout=1)


def test_changed_split_assignment_is_detected_even_with_rehashed_final_cases():
    data = packet()
    result = apply_source_review(data, completed_review(data))
    result["cases"][0]["split"] = "heldout" if result["cases"][0]["split"] == "development" else "development"
    result["split_manifest"]["case_hashes"] = {case["case_id"]: fingerprint(case) for case in result["cases"]}
    rehash(result)
    assert "split_case_identity_changed" in source_comparison_readiness(result, min_heldout=1)["reason_codes"]


def test_blind_html_escapes_source_text_and_has_no_execution_channel():
    rows = records(1)
    text = '</script><img src=x onerror="alert(1)">'
    rows[0]["source"]["text"] = text
    rows[0]["provenance"].update(sha256=sha256(text.encode()).hexdigest(), bytes=len(text.encode()))
    data = build_source_review_pack(rows, context())
    html = render_source_review(data)
    assert text not in html and '\\u003c/script\\u003e' in html
    assert 'innerHTML' not in html and "connect-src 'none'" in html
    assert 'model_answer' not in html
