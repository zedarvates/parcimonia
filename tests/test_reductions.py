"""Check the reduction against source semantics, not its implementation steps."""

from copy import deepcopy
from itertools import product
import random

import pytest

from tiberium_ai.reductions import (
    CONSTRAINTS_QUESTION,
    OBSERVATIONS_QUESTION,
    REDUCTION_ID,
    REDUCTION_VERSION,
    reduce_to_2cnf,
    register_reduction_verifier,
)
from tiberium_ai.verification import VerifierRegistry, hash_input


def _request(variables=("a", "b"), constraints=()):
    return {
        "schema": "parcimonia.feasibility-request/v1",
        "task_id": "reduction-fixture",
        "scope_id": "authored-fixture",
        "revision": "fixture-v1",
        "variables": list(variables),
        "constraints": list(constraints),
        "observations": [],
        "criteria": [],
    }


def _require(identity, variable, value):
    return {
        "id": identity, "kind": "require", "variable": variable,
        "value": value, "source": "fixture:" + identity,
    }


def _implies(identity, before, after, before_value=True, after_value=True):
    return {
        "id": identity, "kind": "implies",
        "if": {"variable": before, "value": before_value},
        "then": {"variable": after, "value": after_value},
        "source": "fixture:" + identity,
    }


def _observe(variable, value):
    return {
        "variable": variable, "value": value,
        "source": "fixture:observation:" + variable, "revision": "fixture-v1",
    }


def _source_accepts(request, assignment, *, observations=False):
    """Independent, declarative source oracle on one complete assignment."""
    for constraint in request["constraints"]:
        if constraint["kind"] == "require":
            if assignment[constraint["variable"]] != constraint["value"]:
                return False
        else:
            antecedent, consequence = constraint["if"], constraint["then"]
            if (
                assignment[antecedent["variable"]] == antecedent["value"]
                and assignment[consequence["variable"]] != consequence["value"]
            ):
                return False
    if observations:
        for observation in request["observations"]:
            if observation["value"] is not None and (
                assignment[observation["variable"]] != observation["value"]
            ):
                return False
    return True


def _target_accepts(target, assignment):
    names = target["variables"]
    return all(
        any(assignment[names[abs(number) - 1]] == (number > 0) for number in clause)
        for clause in target["clauses"]
    )


def _check_every_assignment(request, include_observations=False):
    report = reduce_to_2cnf(request, include_observations=include_observations)
    assert report["status"] == "reduced"
    for values in product((False, True), repeat=len(request["variables"])):
        assignment = dict(zip(request["variables"], values))
        assert _source_accepts(
            request, assignment, observations=include_observations
        ) == _target_accepts(report["target"], assignment)
    return report


@pytest.mark.parametrize("value", [False, True])
def test_unit_requirements_preserve_all_assignments(value):
    report = _check_every_assignment(_request(constraints=[_require("goal", "a", value)]))
    assert report["target"]["clauses"] == [[1 if value else -1]]
    assert report["source_question"] == CONSTRAINTS_QUESTION


@pytest.mark.parametrize("before_value,after_value", tuple(product((False, True), repeat=2)))
@pytest.mark.parametrize("same_variable", [False, True])
def test_implications_preserve_all_signs_and_self_relations(
    before_value, after_value, same_variable
):
    after = "a" if same_variable else "b"
    _check_every_assignment(_request(constraints=[
        _implies("dependency", "a", after, before_value, after_value)
    ]))


@pytest.mark.parametrize("seed", range(24))
def test_compound_models_match_independent_truth_table(seed):
    rng = random.Random(seed)
    variables = ("a", "b", "c", "d")
    constraints = []
    for index in range(7):
        if rng.randrange(3) == 0:
            constraints.append(_require(str(index), rng.choice(variables), bool(rng.randrange(2))))
        else:
            constraints.append(_implies(
                str(index), rng.choice(variables), rng.choice(variables),
                bool(rng.randrange(2)), bool(rng.randrange(2)),
            ))
    request = _request(variables, constraints)
    request["observations"] = [_observe("a", bool(seed % 2)), _observe("b", None)]
    _check_every_assignment(request)
    _check_every_assignment(request, True)


def test_observation_projection_is_explicit_and_unknown_is_not_false():
    request = _request(constraints=[_require("goal", "a", True)])
    request["observations"] = [_observe("a", False), _observe("b", None)]
    hard = _check_every_assignment(request)
    current = _check_every_assignment(request, True)
    assert hard["target"]["clauses"] == [[1]]
    assert current["target"]["clauses"] == [[1], [-1]]
    assert current["source_question"] == OBSERVATIONS_QUESTION
    assert current["unknown_observations"] == ["b"]
    assert current["clause_origins"][-1] == {
        "clause_index": 1, "kind": "observation", "variable": "a",
        "source": "fixture:observation:a",
    }


def test_criteria_do_not_secretly_become_constraints():
    request = _request()
    request["criteria"] = [{"id": "quality", "status": "fail", "source": "fixture:quality"}]
    report = _check_every_assignment(request, True)
    assert report["target"]["clauses"] == []
    assert report["limits"]["criteria"] == "not_part_of_source_question"


def test_canonical_target_and_origins_do_not_depend_on_input_order():
    request = _request(("b", "a"), [
        _implies("z", "a", "b"), _require("a", "a", True)
    ])
    request["observations"] = [_observe("b", True), _observe("a", True)]
    first = reduce_to_2cnf(request, include_observations=True)
    reordered = deepcopy(request)
    for field in ("variables", "constraints", "observations"):
        reordered[field].reverse()
    second = reduce_to_2cnf(reordered, include_observations=True)
    assert first["target"] == second["target"]
    assert first["target_hash"] == second["target_hash"]
    assert first["clause_origins"] == second["clause_origins"]
    assert first["input_hash"] != second["input_hash"]


def test_empty_model_has_one_compatible_empty_assignment():
    report = _check_every_assignment(_request((), []))
    assert report["target"] == {
        "schema": "parcimonia.2cnf/v1", "variables": [], "clauses": []
    }


def test_unsupported_constraint_abstains_for_the_entire_reduction():
    request = _request(constraints=[
        _require("yes", "a", True), _require("no", "a", False),
        {"id": "future", "kind": "resource-limit", "source": "fixture:future"},
    ])
    report = reduce_to_2cnf(request)
    assert report["status"] == "indeterminate"
    assert report["target"] is None
    assert report["target_hash"] is None
    assert report["clause_origins"] == []
    assert report["unsupported_constraint_ids"] == ["future"]
    assert report["reason_codes"] == ["unsupported_constraint_kind"]


@pytest.mark.parametrize("flag", [0, 1, None, "true", []])
def test_include_observations_has_no_truthiness_coercion(flag):
    with pytest.raises(ValueError):
        reduce_to_2cnf(_request(), include_observations=flag)


@pytest.mark.parametrize("mutation", [
    lambda r: r["variables"].append("a"),
    lambda r: r["constraints"].append(_require("bad", "missing", True)),
    lambda r: r["constraints"].append(_require("bad", "a", 1)),
    lambda r: r.update(extra=True),
    lambda r: r["observations"].append({**_observe("a", True), "revision": "stale"}),
])
def test_shared_source_validation_is_preserved(mutation):
    request = _request()
    mutation(request)
    with pytest.raises(ValueError):
        reduce_to_2cnf(request)


def test_reduction_handles_128_variables_without_enumeration(monkeypatch):
    import tiberium_ai.feasibility as feasibility

    def forbidden(*args, **kwargs):
        raise AssertionError("exhaustive solver must not be used by the reduction")

    monkeypatch.setattr(feasibility, "diagnose", forbidden)
    monkeypatch.setattr(feasibility.itertools, "product", forbidden)
    variables = [f"v{index:03d}" for index in range(128)]
    request = _request(variables, [
        _implies(f"dependency-{index:03d}", variables[index], variables[index + 1])
        for index in range(127)
    ])
    report = reduce_to_2cnf(request)
    assert report["status"] == "reduced"
    assert len(report["target"]["variables"]) == 128
    assert len(report["target"]["clauses"]) == 127
    assert report["target"]["clauses"][-1] == [-127, 128]


def test_translation_does_not_modify_or_alias_caller_input():
    request = _request(constraints=[_require("goal", "a", True)])
    before = deepcopy(request)
    report = reduce_to_2cnf(request)
    assert request == before
    assert report["input_hash"] == hash_input(request)
    report["target"]["variables"].append("external")
    report["target"]["clauses"][0][0] = -1
    assert request == before


@pytest.mark.parametrize("include_observations", [False, True])
def test_reduction_replay_is_attributed_not_a_sat_verdict(include_observations):
    request = _request(constraints=[_require("yes", "a", True), _require("no", "a", False)])
    registry = VerifierRegistry()
    register_reduction_verifier(registry)
    report = reduce_to_2cnf(request, include_observations=include_observations)
    result = registry.verify(REDUCTION_ID, REDUCTION_VERSION, {"request": request, "report": report})
    assert result.verdict is True
    assert result.verifier_id == REDUCTION_ID
    assert report["status"] == "reduced"  # Unsatisfiable is not failed translation.


@pytest.mark.parametrize("mutation", [
    lambda r: r["target"]["clauses"][0].__setitem__(0, -1),
    lambda r: r["target"]["clauses"][0].__setitem__(0, True),
    lambda r: r["clause_origins"][0].update(source="forged"),
    lambda r: r.update(input_hash="0" * 64),
    lambda r: r.update(target_hash="0" * 64),
    lambda r: r.update(extra=True),
    lambda r: r.update(source_question="unknown_question"),
])
def test_replay_rejects_target_provenance_and_question_forgery(mutation):
    request = _request(constraints=[_require("goal", "a", True)])
    report = reduce_to_2cnf(request)
    mutation(report)
    registry = VerifierRegistry()
    register_reduction_verifier(registry)
    assert registry.verify(
        REDUCTION_ID, REDUCTION_VERSION, {"request": request, "report": report}
    ).verdict is False


def test_replay_preserves_indeterminate_and_rejects_malformed_envelopes():
    request = _request(constraints=[{"id": "future", "kind": "future", "source": "fixture:future"}])
    registry = VerifierRegistry()
    register_reduction_verifier(registry)
    report = reduce_to_2cnf(request)
    assert registry.verify(REDUCTION_ID, REDUCTION_VERSION, {"request": request, "report": report}).verdict is True
    for value in ({}, {"request": request, "report": report, "extra": 1}, {"request": request, "report": []}):
        assert registry.verify(REDUCTION_ID, REDUCTION_VERSION, value).verdict is False
