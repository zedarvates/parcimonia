import json
from copy import deepcopy

import pytest

from tiberium_ai.contracts import CandidateRoute, Evidence, Task
from tiberium_ai.observations import (
    compare_observation,
    read_observation,
    record_observation,
    replay_observation,
    write_observation,
)
from tiberium_ai.verification import (
    VerifierRegistry,
    attributed_evidence,
    shape_verifier,
)


def attributed_side(
    task_id,
    route_id,
    value,
    latency=None,
    cost=None,
    verifier_id="shape",
    version="1",
):
    registry = VerifierRegistry()
    registry.register("shape", "1", shape_verifier({"answer": "str"}))
    verification = registry.verify(verifier_id, version, value)
    return attributed_evidence(
        verification,
        task_id=task_id,
        route_id=route_id,
        measured_latency_ms=latency,
        measured_cost=cost,
    )


def example_record(**overrides):
    arguments = dict(
        baseline_route_id="baseline",
        cost_unit="synthetic-unit/task",
        data_origin="synthetic",
        min_confidence=0.94,
        baseline_evidence=Evidence("t1", "baseline", True, 100, 8),
        proposal_evidence=Evidence("t1", "rule", True, 20, 3),
    )
    arguments.update(overrides)
    return record_observation(
        Task("t1", "format", {"secret": "PRIVATE_TASK_INPUT"}),
        [
            CandidateRoute("baseline", ["model:baseline"], 10, 120, 0.99),
            CandidateRoute("rule", ["rule:format"], 2, 30, 0.95),
        ],
        **arguments,
    )


def test_record_round_trip_replays_custom_configuration(tmp_path):
    record = example_record()
    path = tmp_path / "observation.json"
    write_observation(path, record)
    restored = read_observation(path)
    assert restored == record
    decision = replay_observation(restored)
    assert decision.selected_route_id == "rule"
    assert decision.mode == "shadow"
    assert restored["router"]["min_confidence"] == 0.94


def test_record_snapshots_candidates_and_omits_sensitive_payloads():
    capability_ids = ["rule:format"]
    record = record_observation(
        Task("t1", "format", {"password": "PRIVATE_INPUT"}),
        [CandidateRoute("rule", capability_ids, 2, confidence=1,
                        known_failure_modes=["PRIVATE_FAILURE_DESCRIPTION"])],
        baseline_route_id="rule", cost_unit="unit/task", data_origin="caller_reported",
        baseline_evidence=Evidence("t1", "rule", True, metadata={"token": "PRIVATE_TOKEN"}),
    )
    capability_ids.append("later-change")
    encoded = json.dumps(record)
    assert "PRIVATE" not in encoded
    assert "inputs" not in record["task"]
    assert record["candidates"][0]["capability_ids"] == ["rule:format"]
    assert record["data_origin"] == "caller_reported"


def test_estimates_and_measurements_remain_separate():
    result = compare_observation(example_record())
    assert result["estimated_cost_delta"] == 8
    assert result["measured_cost_delta"] == 5
    assert result["measured_latency_delta_ms"] == 80
    # Version 1 evidence carries a caller assertion without verifier identity.
    assert result["status"] == "unattributed_evidence"
    assert result["data_origin"] == "synthetic"
    assert result["cost_unit"] == "synthetic-unit/task"


@pytest.mark.parametrize("overrides,status", [
    ({"proposal_evidence": None}, "insufficient_evidence"),
    ({"baseline_evidence": None}, "insufficient_evidence"),
    ({"proposal_evidence": Evidence("t1", "rule", False, 1, 0)}, "verification_failed"),
    ({"baseline_evidence": Evidence("t1", "baseline", False, 100, 8)}, "verification_failed"),
])
def test_unverified_or_missing_evidence_never_produces_measured_deltas(overrides, status):
    result = compare_observation(example_record(**overrides))
    assert result["status"] == status
    assert result["estimated_cost_delta"] == 8
    assert result["measured_cost_delta"] is None
    assert result["measured_latency_delta_ms"] is None


def test_missing_measurements_are_not_filled_from_estimates():
    result = compare_observation(example_record(
        proposal_evidence=Evidence("t1", "rule", True),
    ))
    assert result["measured_cost_delta"] is None
    assert result["measured_latency_delta_ms"] is None


def test_negative_measured_delta_reports_a_regression():
    result = compare_observation(example_record(
        proposal_evidence=Evidence("t1", "rule", True, 150, 12),
    ))
    assert result["measured_cost_delta"] == -4
    assert result["measured_latency_delta_ms"] == -50


def test_zero_measured_cost_is_preserved():
    result = compare_observation(example_record(
        proposal_evidence=Evidence("t1", "rule", True, 0, 0),
    ))
    assert result["measured_cost_delta"] == 8
    assert result["measured_latency_delta_ms"] == 100


def test_unknown_estimate_does_not_use_measurement_as_estimate():
    record = example_record()
    record["candidates"][0]["estimated_cost"] = None
    result = compare_observation(record)
    assert result["estimated_cost_delta"] is None
    assert result["measured_cost_delta"] == 5


def test_abstention_can_be_recorded_and_replayed():
    record = record_observation(
        Task("t1", "format", {}),
        [CandidateRoute("baseline", ["model"], confidence=None)],
        baseline_route_id="baseline", cost_unit="unit/task", data_origin="synthetic",
    )
    assert replay_observation(record).abstained
    result = compare_observation(record)
    assert result["status"] == "abstained"
    assert result["estimated_cost_delta"] is None
    assert result["measured_cost_delta"] is None


def test_baseline_selected_is_not_reported_as_an_alternative_saving():
    record = example_record(min_confidence=0.98, proposal_evidence=None)
    assert replay_observation(record).selected_route_id == "baseline"
    result = compare_observation(record)
    assert result["status"] == "baseline_selected"
    assert result["estimated_cost_delta"] == 0
    assert result["measured_cost_delta"] is None


@pytest.mark.parametrize("evidence", [
    Evidence("different-task", "rule", True, 1, 1),
    Evidence("t1", "different-route", True, 1, 1),
    Evidence("t1", "rule", "true", 1, 1),
    Evidence("t1", "rule", True, -1, 1),
    Evidence("t1", "rule", True, 1, float("nan")),
    Evidence("t1", "rule", True, 1, True),
])
def test_unbound_or_invalid_measurements_are_rejected(evidence):
    with pytest.raises(ValueError):
        example_record(proposal_evidence=evidence)


def test_proposal_evidence_must_match_the_actual_proposal():
    with pytest.raises(ValueError):
        example_record(min_confidence=1, proposal_evidence=Evidence("t1", "rule", True))


@pytest.mark.parametrize("field,value", [
    ("schema_version", 3), ("schema_version", True),
    ("data_origin", "made-up"), ("cost_unit", ""),
    ("baseline_route_id", "absent"),
])
def test_unsupported_or_incoherent_records_are_rejected(field, value):
    record = example_record()
    record[field] = value
    with pytest.raises(ValueError):
        replay_observation(record)


@pytest.mark.parametrize("mutation", ["policy-version", "threshold", "decision", "mode", "extra-key"])
def test_changed_policy_or_forged_decision_is_rejected(mutation):
    record = example_record()
    if mutation == "policy-version":
        record["router"]["policy_version"] = "future-policy"
    elif mutation == "threshold":
        record["router"]["min_confidence"] = 0.98
    elif mutation == "decision":
        record["decision"]["selected_route_id"] = "baseline"
    elif mutation == "mode":
        record["decision"]["mode"] = "active"
    else:
        record["task"]["inputs"] = {"private": "payload"}
    with pytest.raises(ValueError):
        replay_observation(record)


def test_write_is_non_destructive(tmp_path):
    path = tmp_path / "observation.json"
    path.write_text("existing-content", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_observation(path, example_record())
    assert path.read_text(encoding="utf-8") == "existing-content"


def test_write_requires_an_existing_directory(tmp_path):
    path = tmp_path / "missing" / "observation.json"
    with pytest.raises(FileNotFoundError):
        write_observation(path, example_record())
    assert not path.exists()


def test_invalid_record_is_rejected_before_creating_file(tmp_path):
    record = example_record()
    record["proposal_evidence"]["measured_cost"] = -2
    path = tmp_path / "invalid.json"
    with pytest.raises(ValueError):
        write_observation(path, record)
    assert not path.exists()


@pytest.mark.parametrize("invalid_json", [
    '{"schema_version": 1, "schema_version": 2}',
    '{"schema_version": NaN}', '[1, 2]', '{broken',
])
def test_reader_rejects_ambiguous_or_malformed_json(tmp_path, invalid_json):
    path = tmp_path / "invalid.json"
    path.write_text(invalid_json, encoding="utf-8")
    with pytest.raises(ValueError):
        read_observation(path)


def test_comparison_does_not_modify_record():
    record = example_record()
    original = deepcopy(record)
    compare_observation(record)
    assert record == original


CANDIDATES = [
    CandidateRoute("baseline", ["model"], 10, 120, 0.99),
    CandidateRoute("rule", ["rule"], 2, 30, 0.95),
]


def attributed_record(**overrides):
    arguments = dict(
        baseline_evidence=attributed_side("t1", "baseline", {"answer": "ok"}, 100, 8),
        proposal_evidence=attributed_side("t1", "rule", {"answer": "ok"}, 20, 3),
    )
    arguments.update(overrides)
    return record_observation(
        Task("t1", "format", {}),
        [CandidateRoute(c.route_id, list(c.capability_ids), c.estimated_cost,
                        c.estimated_latency_ms, c.confidence) for c in CANDIDATES],
        baseline_route_id="baseline",
        cost_unit="unit/task",
        data_origin="synthetic",
        **arguments,
    )


def test_attributed_evidence_produces_a_version_two_record():
    record = attributed_record()
    assert record["schema_version"] == 2
    assert "verification" in record["baseline_evidence"]
    assert "verifier_ok" not in record["baseline_evidence"]
    blocked = record["baseline_evidence"]["verification"]
    assert blocked["verifier_id"] == "shape"
    assert blocked["verifier_version"] == "1"
    assert blocked["verdict"] is True
    result = compare_observation(record)
    assert result["status"] == "verified_evidence"
    assert result["measured_cost_delta"] == 5
    assert result["measured_latency_delta_ms"] == 80


def test_mixing_attributed_and_unattributed_evidence_is_rejected():
    with pytest.raises(ValueError, match="attributed"):
        attributed_record(
            baseline_evidence=Evidence("t1", "baseline", True, 100, 8),
        )


def test_rejected_verification_withholds_measured_deltas():
    record = attributed_record(
        proposal_evidence=attributed_side("t1", "rule", {"answer": 1}, 20, 3),
    )
    result = compare_observation(record)
    assert result["status"] == "verification_failed"
    assert result["estimated_cost_delta"] == 8
    assert result["measured_cost_delta"] is None


def test_abstained_verification_is_stored_and_withholds_measured_deltas():
    record = attributed_record(
        baseline_evidence=attributed_side(
            "t1", "baseline", {"answer": "ok"}, 100, 8, verifier_id="absent"
        ),
        proposal_evidence=attributed_side(
            "t1", "rule", {"answer": "ok"}, 20, 3, verifier_id="absent"
        ),
    )
    assert record["baseline_evidence"]["verification"]["verdict"] is None
    assert (
        record["baseline_evidence"]["verification"]["detail_code"]
        == "unregistered_verifier"
    )
    result = compare_observation(record)
    assert result["status"] == "verification_abstained"
    assert result["measured_cost_delta"] is None
    assert result["measured_latency_delta_ms"] is None


def test_version_two_requires_a_complete_verifier_block():
    record = attributed_record()
    del record["baseline_evidence"]["verification"]["input_hash"]
    with pytest.raises(ValueError):
        replay_observation(record)


def test_version_two_rejects_a_malformed_input_hash():
    record = attributed_record()
    record["baseline_evidence"]["verification"]["input_hash"] = "short"
    with pytest.raises(ValueError):
        replay_observation(record)


def test_version_two_rejects_version_one_evidence():
    record = example_record()
    record["schema_version"] = 2
    with pytest.raises(ValueError):
        replay_observation(record)
