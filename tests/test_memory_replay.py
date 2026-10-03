import copy
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import pytest

from tiberium_ai.benchmark import run_benchmark
from tiberium_ai.compact_memory import MemoryLimits
from tiberium_ai.measurement import Environment
from tiberium_ai.memory_replay import VersionedFactArchive, build_memory_replay_cases, read_jsonl
from tiberium_ai.verification import hash_input

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "memory_replay.py"


def archive():
    return VersionedFactArchive([
        {"entity_id": "alpha", "key": "budget", "source_version": "v1", "value": 10},
        {"entity_id": "alpha", "key": "budget", "source_version": "v2", "value": 20},
        {"entity_id": "beta", "key": "budget", "source_version": "v1", "value": 30},
    ])


def sequence(case_id="episode-a", *, origin="authored", critical=False):
    def turn(index):
        return {"task": {"task_id": f"request-{index}", "kind": "choose", "inputs": {
            "entity_id": "alpha", "source_version": "v1", "private_note": "PRIVATE-FIXTURE-MARKER"}},
            "required_keys": ["budget"], "routing_epoch": "tools-v1", "critical_change": critical and index == 1,
            "candidates": [
                {"route_id": "a", "capability_ids": ["solve"], "estimated_cost": 1.0 if index == 0 else 1.01, "confidence": 0.95},
                {"route_id": "b", "capability_ids": ["solve"], "estimated_cost": 1.01 if index == 0 else 1.0, "confidence": 0.95},
            ]}
    return {"schema": "memory-sequence/1", "sequence_id": case_id, "origin": origin,
            "source_ref": "fixture-source-v1", "producer_id": "fixture-producer",
            "initial_history": ["Earlier discussion. " * 20], "turns": [turn(0), turn(1)]}


def outcomes(seq, *, labeller="fixture-author", origin="authored"):
    return {"schema": "memory-outcomes/1", "sequence_id": seq["sequence_id"],
            "sequence_hash": hash_input(seq), "archive_revision": archive().revision,
            "source_ref": "fixture-oracle-v1", "labeller_id": labeller, "origin": origin,
            "turns": [
                {"task_id": "request-0", "facts": {"budget": 10}, "missing": [], "allowed_routes": ["a"]},
                {"task_id": "request-1", "facts": {"budget": 10}, "missing": [],
                 "allowed_routes": ["b"] if seq["turns"][1]["critical_change"] else ["a", "b"]},
            ]}


def run(cases, out):
    return run_benchmark(cases, out_dir=out, seed=20261003, environment=Environment("fixture", {}),
                         clock=perf_counter, cost_unit="unmeasured", corpus="authored-replay-test")


def test_versioned_archive_pins_exact_json_and_detaches_mutable_values():
    rows = [{"entity_id": "a", "key": "x", "source_version": "v1", "value": {"items": [0, False]}}]
    source = VersionedFactArchive(rows)
    rows[0]["value"]["items"].append("mutated")
    item = source.source("a", "x", "v1")
    assert item.value == {"items": [0, False]}
    item.value["items"].append("changed")
    assert source.source("a", "x", "v1").value == {"items": [0, False]}
    assert source.source("b", "x", "v1") is None
    assert source.source("a", "x", "v2") is None
    bad = copy.deepcopy(rows[0])
    bad["value"] = 999
    with pytest.raises(ValueError, match="immutable"):
        VersionedFactArchive([rows[0], bad])
    assert archive().source("alpha", "budget", "v2").value == 20


def test_replay_isolates_sequences_and_preserves_critical_switch_and_restart(tmp_path):
    jitter, critical = sequence(), sequence("episode-b", critical=True)
    critical["turns"][1]["restart"] = True
    outputs = {}
    cases, provenance = build_memory_replay_cases([jitter, critical], archive(),
        outcomes=[outcomes(jitter), outcomes(critical)], outputs=outputs, relative_cost_margin=0.02)
    report = run(cases, tmp_path)
    assert all(r["accepted"] == 2 for r in report["routes"].values())
    assert outputs["episode-a"]["compact"]["turns"][1]["selected_route_id"] == "b"
    assert outputs["episode-a"]["compact_persistent"]["turns"][1]["selected_route_id"] == "a"
    assert outputs["episode-b"]["compact_persistent"]["turns"][1]["selected_route_id"] == "b"
    assert set(provenance["label_status"].values()) == {"authored_labels"}
    assert provenance["production_saving_claim"]["status"] == "refused"
    assert set(report["split"]["development"]) & set(report["split"]["heldout"]) == set()


def test_missing_and_self_attributed_outcomes_produce_no_verdict(tmp_path):
    a, b = sequence(origin="captured"), sequence("episode-b", origin="captured")
    own = outcomes(b, labeller=b["producer_id"], origin="outcomes")
    cases, provenance = build_memory_replay_cases([a, b], archive(), outcomes=[own])
    assert provenance["label_status"] == {"episode-a": "missing_outcomes", "episode-b": "dependent_labels"}
    report = run(cases, tmp_path)
    assert all(r["accepted"] == 0 and r["no_verdict"] == 2 for r in report["routes"].values())
    assert report["claim"]["status"] == "refused"


def test_independent_declared_outcomes_are_distinct_from_authored_labels():
    seq = sequence(origin="captured")
    cases, provenance = build_memory_replay_cases([seq], archive(), outcomes=[outcomes(seq, origin="outcomes")])
    assert provenance["label_status"]["episode-a"] == "declared_outcomes"
    assert cases[0].verifier is not None
    assert provenance["production_saving_claim"]["status"] == "refused"


@pytest.mark.parametrize("change", ["sequence", "archive", "partial", "facts_partition", "route"])
def test_mismatched_or_incomplete_labels_are_rejected_before_execution(change):
    seq = sequence()
    label = outcomes(seq)
    if change == "sequence":
        label["sequence_hash"] = "0" * 64
    elif change == "archive":
        label["archive_revision"] = "0" * 64
    elif change == "partial":
        label["turns"].pop()
    elif change == "facts_partition":
        label["turns"][0]["missing"] = ["budget"]
    else:
        label["turns"][0]["allowed_routes"] = ["unknown"]
    with pytest.raises(ValueError):
        build_memory_replay_cases([seq], archive(), outcomes=[label])


def test_oracle_rejects_wrong_facts_and_an_ignored_critical_change():
    seq = sequence(critical=True)
    outputs = {}
    cases, _ = build_memory_replay_cases([seq], archive(), outcomes=[outcomes(seq)], outputs=outputs)
    result = cases[0].routes[2].run()
    assert cases[0].verifier(result)
    bad = copy.deepcopy(result)
    bad["turns"][1]["selected_route_id"] = "a"
    assert not cases[0].verifier(bad)
    bad = copy.deepcopy(result)
    bad["turns"][0]["facts"]["budget"] = 11
    assert not cases[0].verifier(bad)


@pytest.mark.parametrize("bad_id", ["../escape", "/absolute", "..", "private/path"])
def test_sequence_ids_cannot_escape_the_measurement_directory(bad_id):
    with pytest.raises(ValueError, match="filename-safe"):
        build_memory_replay_cases([sequence(bad_id)], archive())


@pytest.mark.parametrize("text", ['{"private":"secret","private":"different"}', '{"value":NaN}', '[1,2]'])
def test_jsonl_rejects_ambiguous_or_nonfinite_records_without_echoing_payload(tmp_path, text):
    path = tmp_path / "input.jsonl"
    path.write_text(text)
    with pytest.raises(ValueError, match="line 1") as exc:
        read_jsonl(path)
    assert "secret" not in str(exc.value)


def write_inputs(tmp_path):
    sequences = [sequence(), sequence("episode-b", critical=True)]
    facts = [{"entity_id": e, "key": "budget", "source_version": v, "value": value}
             for e, v, value in [("alpha", "v1", 10), ("alpha", "v2", 20), ("beta", "v1", 30)]]
    for name, rows in [("sequences", sequences), ("facts", facts), ("outcomes", [outcomes(s) for s in sequences])]:
        (tmp_path / (name + ".jsonl")).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return sequences


def cli(tmp_path, *, labelled=True):
    args = [sys.executable, str(SCRIPT), "--sequences", str(tmp_path / "sequences.jsonl"),
            "--archive", str(tmp_path / "facts.jsonl"), "--out", str(tmp_path / "replay")]
    if labelled:
        args.extend(["--outcomes", str(tmp_path / "outcomes.jsonl")])
    return subprocess.run(args, capture_output=True, text=True)


def test_cli_uses_normal_measurements_keeps_sources_private_and_refuses_overwrite(tmp_path):
    write_inputs(tmp_path)
    before = (tmp_path / "sequences.jsonl").read_bytes()
    result = cli(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "PRIVATE-FIXTURE-MARKER" not in result.stdout + result.stderr
    report_path = tmp_path / "replay" / "report.json"
    report = json.loads(report_path.read_text())
    assert all(v["accepted"] == 2 for v in report["routes"].values())
    assert len(list((tmp_path / "replay" / "measurements").glob("*.json"))) == 6
    for path in (tmp_path / "replay").rglob("*.json"):
        assert "PRIVATE-FIXTURE-MARKER" not in path.read_text()
    assert (tmp_path / "sequences.jsonl").read_bytes() == before
    report_before = report_path.read_bytes()
    assert cli(tmp_path).returncode == 2
    assert report_path.read_bytes() == report_before


def test_cli_can_replay_without_labels_and_cannot_invent_success(tmp_path):
    write_inputs(tmp_path)
    result = cli(tmp_path, labelled=False)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "replay" / "report.json").read_text())
    assert all(v["accepted"] == 0 and v["no_verdict"] == 2 for v in report["routes"].values())
    assert report["memory_replay"]["production_saving_claim"]["status"] == "refused"


def test_failed_context_budget_is_recorded_and_not_counted_as_zero_bytes(tmp_path):
    seq = sequence()
    outputs = {}
    cases, _ = build_memory_replay_cases([seq], archive(), limits=MemoryLimits(max_context_bytes=100), outputs=outputs)
    report = run(cases, tmp_path)
    assert report["routes"]["compact"]["failed"] == 1
    assert "compact" not in outputs["episode-a"]
