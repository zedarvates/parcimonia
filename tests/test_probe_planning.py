"""Planning declarations do not attest a test, a cause or a completed mission."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tiberium_ai.execution_profiles import digest
from tiberium_ai.probe_planning import plan_observation_probes

from test_observation_review import observation, probe, request, requirement


NOW = 1000


def model(value, **changes):
    result = {"schema": "parcimonia.probe-planning-model/v1",
              "task_id": value["task_id"], "task_revision": value["task_revision"],
              "revision": "authored-1", "observation_request_sha256": digest(value),
              "cost_unit": "authored-unit", "hypothesis_ids": ["a", "b", "c", "d"],
              "probes": [probe_model(row["id"]) for row in value["probes"]]}
    result.update(changes)
    return result


def probe_model(identifier, **changes):
    result = {"id": identifier, "estimated_cost": 1, "unmodelled_outcome_possible": False,
              "outcomes": [{"id": "x", "hypothesis_ids": ["a", "b"]},
                           {"id": "y", "hypothesis_ids": ["c", "d"]}]}
    result.update(changes)
    return result


def missing(*probes):
    return request(observations=[], probes=list(probes or (probe(),)))


def plan(value, declaration=None, **changes):
    return plan_observation_probes(value, model(value) if declaration is None else declaration,
                                   now=NOW, **changes)


def test_one_useful_current_probe_is_a_proposal_never_an_execution():
    value = missing()
    declaration = model(value)
    original = deepcopy((value, declaration))
    result = plan(value, declaration)
    assert result["status"] == "proposed"
    assert result["next_probe"]["id"] == "read-server"
    assert result["next_probe"]["worst_case_remaining_hypotheses"] == 2
    assert result["next_probe"]["worst_case_eliminated_hypotheses"] == 2
    assert result["frontier_probe_ids"] == ["read-server"]
    assert result["observation_review"]["status"] == "needs_observation"
    assert result["model_trust"] == "host_declared_not_independently_verified"
    assert result["measured_savings"] is None
    for name in ("auto_act_allowed", "reservation_performed", "execution_performed"):
        assert result[name] is False
    assert (value, declaration) == original
    assert json.loads(json.dumps(result)) == result
    unsigned = {key: value for key, value in result.items() if key != "report_sha256"}
    assert result["report_sha256"] == digest(unsigned)
    assert result["observation_review_sha256"] == digest(result["observation_review"])


def test_balanced_partition_beats_same_cost_unbalanced_partition():
    value = missing(probe("balanced"), probe("unbalanced"))
    declaration = model(value)
    declaration["probes"][1]["outcomes"] = [
        {"id": "x", "hypothesis_ids": ["a", "b", "c"]}, {"id": "y", "hypothesis_ids": ["d"]}]
    result = plan(value, declaration)
    assert result["next_probe"]["id"] == "balanced"
    assert result["candidates"][1]["worst_case_eliminated_hypotheses"] == 1


def test_tradeoff_needs_preference_without_summing_cost_and_information():
    value = missing(probe("fast", estimated_latency_ms=1), probe("informative", estimated_latency_ms=20))
    declaration = model(value)
    declaration["probes"][0]["outcomes"] = [
        {"id": "x", "hypothesis_ids": ["a", "b", "c"]}, {"id": "y", "hypothesis_ids": ["d"]}]
    result = plan(value, declaration)
    assert result["frontier_probe_ids"] == ["fast", "informative"]
    assert result["status"] == "needs_preference"
    assert result["next_probe"] is None


@pytest.mark.parametrize("unknown", ["cost", "latency", "both"])
def test_unknown_dimensions_are_incomparable_even_when_both_are_unknown(unknown):
    value = missing(probe("a", estimated_latency_ms=None if unknown != "cost" else 1),
                    probe("b", estimated_latency_ms=None if unknown != "cost" else 2))
    declaration = model(value)
    if unknown != "latency":
        for row in declaration["probes"]:
            row["estimated_cost"] = None
    assert plan(value, declaration)["frontier_probe_ids"] == ["a", "b"]


@pytest.mark.parametrize("dimension,limit,reason", [
    ("cost", 0, "cost_estimate_exceeds_cap"),
    ("latency", 0, "latency_estimate_exceeds_cap"),
])
def test_hard_cap_refuses_an_otherwise_useful_probe(dimension, limit, reason):
    result = plan(missing(), **{"max_estimated_" + ("cost" if dimension == "cost" else "latency_ms"): limit})
    assert result["status"] == "abstained"
    assert result["next_probe"] is None
    assert reason in result["candidates"][0]["reasons"]


@pytest.mark.parametrize("dimension", ["cost", "latency"])
def test_unknown_estimate_is_not_zero_under_a_cap(dimension):
    value = missing(probe(estimated_latency_ms=None if dimension == "latency" else 0))
    declaration = model(value)
    if dimension == "cost":
        declaration["probes"][0]["estimated_cost"] = None
    kwargs = {"max_estimated_cost" if dimension == "cost" else "max_estimated_latency_ms": 0}
    result = plan(value, declaration, **kwargs)
    assert result["status"] == "abstained"
    assert dimension + "_estimate_unknown_under_cap" in result["candidates"][0]["reasons"]


def test_explicit_zero_estimates_fit_zero_caps_and_equal_caps_are_inclusive():
    value = missing(probe(estimated_latency_ms=0))
    declaration = model(value)
    declaration["probes"][0]["estimated_cost"] = 0
    assert plan(value, declaration, max_estimated_cost=0, max_estimated_latency_ms=0)["status"] == "proposed"
    assert plan(missing(), max_estimated_cost=1, max_estimated_latency_ms=2)["status"] == "proposed"


def test_large_mixed_int_float_caps_and_dominance_compare_exactly():
    value = missing(probe("a", estimated_latency_ms=10 ** 18),
                    probe("b", estimated_latency_ms=10 ** 18 - 1))
    declaration = model(value)
    declaration["probes"][0]["estimated_cost"] = float(10 ** 18)
    declaration["probes"][1]["estimated_cost"] = 10 ** 18 - 1
    result = plan(value, declaration, max_estimated_latency_ms=10 ** 18 - 1,
                  max_estimated_cost=10 ** 18 - 1)
    assert result["frontier_probe_ids"] == ["b"]
    assert result["candidates"][0]["reasons"] == ["cost_estimate_exceeds_cap", "latency_estimate_exceeds_cap"]
    assert plan(value, declaration)["frontier_probe_ids"] == ["b"]


def test_an_unmodelled_outcome_makes_conditional_metrics_unknown():
    value = missing()
    declaration = model(value)
    declaration["probes"][0]["unmodelled_outcome_possible"] = True
    result = plan(value, declaration)
    row = result["candidates"][0]
    assert row["worst_case_remaining_hypotheses"] is None
    assert row["worst_case_eliminated_hypotheses"] is None
    assert row["reasons"] == ["unmodelled_outcome_possible"]
    assert result["status"] == "abstained"


def test_a_partition_without_discrimination_is_not_useful():
    value = missing()
    declaration = model(value)
    declaration["probes"][0]["outcomes"] = [{"id": "all", "hypothesis_ids": ["a", "b", "c", "d"]}]
    result = plan(value, declaration)
    assert result["candidates"][0]["worst_case_eliminated_hypotheses"] == 0
    assert result["status"] == "abstained"
    assert result["candidates"][0]["reasons"] == ["no_declared_discrimination"]


def test_partial_models_leave_other_declared_probes_visible_and_unselectable():
    value = missing(probe("a"), probe("b"))
    declaration = model(value, probes=[probe_model("b")])
    result = plan(value, declaration)
    assert result["next_probe"]["id"] == "b"
    assert result["candidates"][0]["reasons"] == ["probe_model_missing"]
    assert result["candidates"][0]["estimated_cost"] is None
    assert plan(value, model(value, probes=[]))["status"] == "abstained"


def test_current_failure_blocks_the_plan_even_with_another_unresolved_requirement():
    value = request(requirements=[requirement(), requirement("spawned")],
                    observations=[observation("earlier"), observation("failure", observed_at=NOW, outcome="fail")],
                    probes=[probe(requirement_ids=["spawned"])])
    result = plan(value)
    assert result["status"] == "blocked"
    assert result["next_probe"] is None
    assert result["frontier_probe_ids"] == []
    assert result["observation_review"]["requirements"][0]["state"] == "fail"
    assert result["candidates"][0]["reasons"] == ["observation_blocked"]


def test_ready_reports_suppress_tests_and_stale_reports_require_a_new_observation():
    value = request(probes=[probe()])
    result = plan(value)
    assert result["status"] == "ready"
    assert result["next_probe"] is None
    assert result["candidates"][0]["reasons"] == ["no_unresolved_requirement"]
    value["observations"][0]["observed_at"] = NOW - 61
    assert plan(value)["status"] == "proposed"


@pytest.mark.parametrize("state", ["missing", "unknown", "conflict"])
def test_unresolved_observation_states_are_preserved_without_becoming_pass(state):
    rows = [] if state == "missing" else [observation(outcome="unknown")]
    if state == "conflict":
        rows = [observation("a"), observation("b", outcome="fail")]
    value = missing()
    value["observations"] = rows
    result = plan(value)
    assert result["observation_review"]["requirements"][0]["state"] == state
    assert result["status"] == "proposed"


def test_old_request_binding_and_mismatched_task_or_revision_are_rejected():
    value = missing()
    declaration = model(value)
    value["probes"][0]["estimated_latency_ms"] = 3
    with pytest.raises(ValueError, match="bind"):
        plan(value, declaration)
    for field in ("task_id", "task_revision", "observation_request_sha256"):
        declaration = model(value)
        declaration[field] = "changed"
        with pytest.raises(ValueError, match="bind"):
            plan(value, declaration)


def test_reordering_does_not_change_front_candidates_or_choice():
    value = missing(probe("b"), probe("a"))
    declaration = model(value)
    first = plan(value, declaration)
    value["probes"].reverse()
    declaration["probes"].reverse()
    declaration["hypothesis_ids"].reverse()
    for row in declaration["probes"]:
        row["outcomes"].reverse()
        for outcome in row["outcomes"]:
            outcome["hypothesis_ids"].reverse()
    declaration["observation_request_sha256"] = digest(value)
    second = plan(value, declaration)
    assert first["candidates"] == second["candidates"]
    assert first["frontier_probe_ids"] == second["frontier_probe_ids"] == ["a", "b"]
    assert first["next_probe"] == second["next_probe"] is None


@pytest.mark.parametrize("corruption", ["missing", "overlap", "unknown", "empty", "duplicate_hypothesis",
                                       "duplicate_outcome", "duplicate_model", "unknown_probe"])
def test_invalid_partitions_and_references_are_refused(corruption):
    value = missing()
    declaration = model(value)
    row = declaration["probes"][0]
    if corruption == "missing": row["outcomes"][0]["hypothesis_ids"].pop()
    elif corruption == "overlap": row["outcomes"][0]["hypothesis_ids"].append("c")
    elif corruption == "unknown": row["outcomes"][0]["hypothesis_ids"][0] = "e"
    elif corruption == "empty": row["outcomes"][0]["hypothesis_ids"] = []
    elif corruption == "duplicate_hypothesis": declaration["hypothesis_ids"].append("a")
    elif corruption == "duplicate_outcome": row["outcomes"][1]["id"] = "x"
    elif corruption == "duplicate_model": declaration["probes"].append(deepcopy(row))
    else: row["id"] = "not-in-request"
    with pytest.raises(ValueError):
        plan(value, declaration)


@pytest.mark.parametrize("bad", [True, -1, float("nan"), float("inf"), 10 ** 18 + 1, "1"])
@pytest.mark.parametrize("location", ["cost", "cost_cap", "latency_cap"])
def test_estimates_and_caps_require_bounded_nonboolean_finite_numbers(bad, location):
    value = missing()
    declaration = model(value)
    kwargs = {}
    if location == "cost": declaration["probes"][0]["estimated_cost"] = bad
    else: kwargs["max_estimated_cost" if location == "cost_cap" else "max_estimated_latency_ms"] = bad
    with pytest.raises(ValueError):
        plan(value, declaration, **kwargs)


@pytest.mark.parametrize("corruption", ["schema", "extra_model_field", "extra_probe_field", "extra_outcome_field",
                                       "flag", "label", "cost_unit", "few_hypotheses", "many_hypotheses",
                                       "many_models", "many_outcomes", "too_deep", "too_large"])
def test_closed_bounded_model_rejects_unsupported_fields_and_sizes(corruption):
    value = missing()
    declaration = model(value)
    if corruption == "schema": declaration["schema"] = "another/v1"
    elif corruption == "extra_model_field": declaration["probability"] = 1
    elif corruption == "extra_probe_field": declaration["probes"][0]["probability"] = 1
    elif corruption == "extra_outcome_field": declaration["probes"][0]["outcomes"][0]["probability"] = 1
    elif corruption == "flag": declaration["probes"][0]["unmodelled_outcome_possible"] = 1
    elif corruption == "label": declaration["revision"] = "x\n"
    elif corruption == "cost_unit": declaration["cost_unit"] = "x" * 129
    elif corruption == "few_hypotheses": declaration["hypothesis_ids"] = ["a"]
    elif corruption == "many_hypotheses": declaration["hypothesis_ids"] = [str(i) for i in range(65)]
    elif corruption == "many_models": declaration["probes"] *= 33
    elif corruption == "many_outcomes": declaration["probes"][0]["outcomes"] *= 33
    elif corruption == "too_deep":
        nested = "value"
        for _ in range(33): nested = [nested]
        declaration["unexpected"] = nested
    else: declaration["unexpected"] = "x" * (1024 ** 2)
    with pytest.raises(ValueError):
        plan(value, declaration)


def test_shared_nested_input_is_refused_within_a_bounded_process():
    # Twenty-five shared binary levels stay below the structural depth limit,
    # but expanding all occurrences would require millions of node visits.
    # A subprocess deadline keeps a future regression from hanging this suite.
    script = '''
import sys
sys.path.insert(0, sys.argv[1])
from test_probe_planning import missing, model, plan
value = missing()
declaration = model(value)
shared = "x"
for _ in range(25):
    shared = [shared, shared]
declaration["probes"][0]["estimated_cost"] = shared
try:
    plan(value, declaration)
except ValueError:
    print("bounded_refusal")
else:
    raise SystemExit("Expected a bounded input refusal")
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).parent)],
        capture_output=True, text=True, timeout=5,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "bounded_refusal"
