"""Authored contract tests; these fixtures are not real usage evidence."""

import copy
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tiberium_ai.memory_capture import MemorySequenceCapture, capture_rows
from tiberium_ai.memory_replay import VersionedFactArchive, build_memory_replay_cases, read_jsonl
from tiberium_ai.verification import hash_input

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "examples" / "memory_capture.py"
REPLAY = ROOT / "examples" / "memory_replay.py"


def capture(**extra):
    return MemorySequenceCapture(sequence_id="episode-a", origin="authored", source_ref="fixture-v1",
                                 producer_id="fixture-author", **extra)


def turn(index=0, version="v1"):
    return {"task": {"task_id": f"turn-{index}", "kind": "choose", "inputs": {
        "entity_id": "alpha", "source_version": version, "note": "PRIVATE-CAPTURE-MARKER"}},
        "required_keys": ["budget"], "routing_epoch": "fixture-tools-v1",
        "candidates": [{"route_id": "a", "capability_ids": ["solve"], "estimated_cost": 1, "confidence": 0.95}]}


def receipt(**overrides):
    return {"receipt_id": "receipt-0", "origin": "authored", "source_ref": "fixture-response-v1",
            "variant": "current", "backend_id": "fixture-backend", "backend_version": "v1",
            "payload_hash": None, **overrides}


def test_export_round_trip_replays_exact_versions_and_retains_no_verdict(tmp_path):
    cap = capture(initial_history=["private prior turn"])
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    cap.record_usage("turn-0", receipt(input_tokens=17, output_tokens=4, latency_ms=2.5, n_retries=1))
    cap.append_turn(turn(1, "v2"), facts={"budget": 20}, missing=[])
    dest = tmp_path / "capture"
    manifest = cap.write(dest)
    seq = read_jsonl(dest / "sequences.jsonl")[0]
    archive = VersionedFactArchive(read_jsonl(dest / "facts.jsonl"))
    usages = read_jsonl(dest / "usage.jsonl")
    assert seq["origin"] == "authored"
    assert usages[0]["sequence_hash"] == manifest["sequence_hash"] == hash_input(seq)
    assert usages[0]["archive_revision"] == archive.revision
    assert usages[0]["turn_hash"] == hash_input(seq["turns"][0])
    assert usages[0]["tokens_total"] == 21
    assert usages[0]["cost"] is None
    assert not (dest / "outcomes.jsonl").exists()
    cases, provenance = build_memory_replay_cases([seq], archive)
    assert cases[0].verifier is None
    assert provenance["label_status"] == {"episode-a": "missing_outcomes"}
    for route in cases[0].routes:
        result = route.run()
        assert [t["facts"]["budget"] for t in result["turns"]] == [10, 20]
        assert result["metrics"]["tokens"] is None
    assert manifest["production_saving_claim"]["status"] == "refused"
    if os.name == "posix":
        assert stat.S_IMODE(dest.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in dest.iterdir())


def test_nested_inputs_facts_and_snapshots_cannot_mutate_the_capture():
    cap = capture()
    request, facts = turn(), {"budget": {"items": [10]}}
    cap.append_turn(request, facts=facts, missing=[])
    request["task"]["inputs"]["entity_id"] = "other"
    facts["budget"]["items"].append(20)
    snapshot = cap.snapshot()
    snapshot["facts"][0]["value"]["items"].append(30)
    assert cap.snapshot()["facts"][0]["value"] == {"items": [10]}
    assert cap.snapshot()["sequence"]["turns"][0]["task"]["inputs"]["entity_id"] == "alpha"


@pytest.mark.parametrize("before,after", [(10, 20), (None, 20), (10, None)])
def test_changed_value_or_absence_under_same_version_is_rejected_atomically(before, after):
    cap = capture()
    cap.append_turn(turn(), facts={} if before is None else {"budget": before},
                    missing=["budget"] if before is None else [])
    original = cap.snapshot()
    with pytest.raises(ValueError, match="immutable"):
        cap.append_turn(turn(1), facts={} if after is None else {"budget": after},
                        missing=["budget"] if after is None else [])
    assert cap.snapshot() == original
    cap.append_turn(turn(1, "v2"), facts={} if after is None else {"budget": after},
                    missing=["budget"] if after is None else [])


def test_null_fact_is_distinct_from_missing_and_same_fact_is_deduplicated():
    cap = capture()
    cap.append_turn(turn(), facts={"budget": None}, missing=[])
    cap.append_turn(turn(1), facts={"budget": None}, missing=[])
    assert len(cap.snapshot()["facts"]) == 1
    with pytest.raises(ValueError, match="immutable"):
        cap.append_turn(turn(2), facts={}, missing=["budget"])


@pytest.mark.parametrize("facts,missing", [({}, []), ({"budget": 10}, ["budget"]),
                                           ({"wrong": 10}, []), ({}, ["budget", "budget"])])
def test_invalid_observed_partition_does_not_add_turn(facts, missing):
    cap = capture()
    with pytest.raises(ValueError):
        cap.append_turn(turn(), facts=facts, missing=missing)
    with pytest.raises(ValueError, match="at least one"):
        cap.snapshot()
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])


def test_turn_and_byte_limits_never_truncate_or_commit_a_failed_append():
    cap = capture(max_turns=1)
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    original = cap.snapshot()
    with pytest.raises(ValueError, match="turn limit"):
        cap.append_turn(turn(1), facts={"budget": 10}, missing=[])
    assert cap.snapshot() == original
    small = capture(max_capture_bytes=1800)
    small.append_turn(turn(), facts={"budget": 10}, missing=[])
    original = small.snapshot()
    big = turn(1)
    big["history_events"] = ["x" * 4000]
    with pytest.raises(ValueError, match="byte limit"):
        small.append_turn(big, facts={"budget": 10}, missing=[])
    assert small.snapshot() == original


def test_duplicate_task_and_unbound_usage_are_rejected():
    cap = capture()
    with pytest.raises(ValueError, match="already captured"):
        cap.record_usage("turn-0", receipt())
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    original = cap.snapshot()
    with pytest.raises(ValueError, match="duplicate task"):
        cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    cap.record_usage("turn-0", receipt())
    with pytest.raises(ValueError, match="duplicate usage"):
        cap.record_usage("turn-0", receipt())
    assert cap.snapshot()["sequence"] == original["sequence"]
    assert len(cap.snapshot()["usage"]) == 1


@pytest.mark.parametrize("change", [{"input_tokens": True}, {"n_retries": -1},
    {"latency_ms": float("nan")}, {"cost": 1}, {"payload_hash": "wrong"},
    {"input_tokens": 2, "output_tokens": 3, "tokens_total": 9},
    {"tokens_saved": 1000}, {"origin": "verified"}])
def test_malformed_usage_cannot_be_stored_or_confused_with_savings(change):
    cap = capture()
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    original = cap.snapshot()
    with pytest.raises((ValueError, TypeError)):
        cap.record_usage("turn-0", receipt(**change))
    assert cap.snapshot() == original


def test_partial_counts_and_total_only_usage_preserve_unknowns():
    cap = capture()
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    cap.record_usage("turn-0", receipt(output_tokens=5))
    cap.record_usage("turn-0", receipt(receipt_id="receipt-1", tokens_total=11,
                                      cost=0.01, cost_unit="USD", payload_hash="0" * 64))
    first, second = cap.snapshot()["usage"]
    assert first["input_tokens"] is None and first["tokens_total"] is None
    assert second["input_tokens"] is None and second["output_tokens"] is None
    assert second["tokens_total"] == 11


def test_receipt_budget_is_atomic():
    cap = capture(max_capture_bytes=1800)
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    cap.record_usage("turn-0", receipt())
    original = cap.snapshot()
    with pytest.raises(ValueError, match="byte limit"):
        cap.record_usage("turn-0", receipt(receipt_id="receipt-1"))
    assert cap.snapshot() == original


def test_empty_fact_archive_replays_all_missing_instead_of_inventing_a_fact(tmp_path):
    cap = capture()
    cap.append_turn(turn(), facts={}, missing=["budget"])
    cap.write(tmp_path / "capture")
    rows = read_jsonl(tmp_path / "capture" / "facts.jsonl", allow_empty=True)
    assert rows == ()
    with pytest.raises(ValueError, match="at least one"):
        read_jsonl(tmp_path / "capture" / "facts.jsonl")
    cases, _ = build_memory_replay_cases([cap.snapshot()["sequence"]], VersionedFactArchive(rows))
    for route in cases[0].routes:
        result = route.run()["turns"][0]
        assert result["facts"] == {} and result["missing"] == ["budget"]
        assert result["abstained"] is True
    result = subprocess.run([sys.executable, str(REPLAY), "--sequences",
        str(tmp_path / "capture" / "sequences.jsonl"), "--archive",
        str(tmp_path / "capture" / "facts.jsonl"), "--out", str(tmp_path / "replay")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "replay" / "report.json").read_text())
    assert all(v["no_verdict"] == 1 for v in report["routes"].values())


def test_writer_refuses_existing_evidence_and_cleans_only_its_failed_new_directory(tmp_path, monkeypatch):
    cap = capture()
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    dest = tmp_path / "capture"
    cap.write(dest)
    original = {p.name: p.read_bytes() for p in dest.iterdir()}
    with pytest.raises(FileExistsError):
        cap.write(dest)
    assert original == {p.name: p.read_bytes() for p in dest.iterdir()}
    original_open = os.open
    def fail(path, flags, mode):
        if Path(path).name == "facts.jsonl":
            raise OSError("PRIVATE-CAPTURE-MARKER")
        return original_open(path, flags, mode)
    monkeypatch.setattr(os, "open", fail)
    with pytest.raises(OSError):
        cap.write(tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
    assert original == {p.name: p.read_bytes() for p in dest.iterdir()}


def test_explicit_cli_preserves_authored_origin_and_never_prints_private_sources(tmp_path):
    rows = [{"schema": "memory-capture-turn/1", "turn": turn(), "facts": {"budget": 10}, "missing": []}]
    source = tmp_path / "turns.jsonl"
    source.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    before = source.read_bytes()
    args = [sys.executable, str(CAPTURE), "--turns", str(source), "--sequence-id", "episode-a",
            "--origin", "authored", "--source-ref", "fixture-v1", "--producer-id", "fixture-author",
            "--out", str(tmp_path / "capture")]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "PRIVATE-CAPTURE-MARKER" not in result.stdout + result.stderr
    assert source.read_bytes() == before
    assert json.loads((tmp_path / "capture" / "manifest.json").read_text())["origin"] == "authored"
    assert not (tmp_path / "capture" / "outcomes.jsonl").exists()
    assert subprocess.run(args, capture_output=True).returncode == 2
    bad = copy.deepcopy(rows[0])
    bad["private_extra"] = "PRIVATE-CAPTURE-MARKER"
    source.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    args[-1] = str(tmp_path / "bad")
    rejected = subprocess.run(args, capture_output=True, text=True)
    assert rejected.returncode == 2
    assert "PRIVATE-CAPTURE-MARKER" not in rejected.stdout + rejected.stderr
    assert not (tmp_path / "bad").exists()


def test_capture_rows_keeps_each_usage_attached_to_its_supplied_turn():
    rows = [{"schema": "memory-capture-turn/1", "turn": turn(), "facts": {"budget": 10},
             "missing": [], "usage": [receipt()]}]
    cap = capture_rows(rows, sequence_id="episode-a", origin="authored", source_ref="fixture-v1",
                       producer_id="fixture-author")
    assert cap.snapshot()["usage"][0]["task_id"] == "turn-0"
