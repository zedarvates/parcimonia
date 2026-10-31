"""Behavioral checks for bounded diagnosis, including an independent SAT oracle.

These authored examples qualify the finite-model contract, not real project
feasibility, source truth or general anomaly-detection accuracy.
"""

from copy import deepcopy
from itertools import product
import json
import random

import pytest

from tiberium_ai.feasibility import diagnose, register_feasibility_verifier
from tiberium_ai.verification import VerifierRegistry, hash_input


def request(variables=("reconnect", "persistence"), constraints=()):
    return {
        "schema": "parcimonia.feasibility-request/v1",
        "task_id": "reconnect-example",
        "scope_id": "authored-fixture",
        "revision": "fixture-1",
        "variables": list(variables),
        "constraints": list(constraints),
        "observations": [],
        "criteria": [],
    }


def require(identity, variable, value):
    return {
        "id": identity,
        "kind": "require",
        "variable": variable,
        "value": value,
        "source": "fixture:" + identity,
    }


def implies(identity, before, after, before_value=True, after_value=True):
    return {
        "id": identity,
        "kind": "implies",
        "if": {"variable": before, "value": before_value},
        "then": {"variable": after, "value": after_value},
        "source": "fixture:" + identity,
    }


def observe(variable, value):
    return {
        "variable": variable,
        "value": value,
        "source": "fixture:observation:" + variable,
        "revision": "fixture-1",
    }


def reconnect_request():
    return request(
        constraints=[
            require("goal", "reconnect", True),
            implies("dependency", "reconnect", "persistence"),
        ]
    )


def test_impossibility_requires_a_contradiction_in_hard_constraints():
    data = request(
        ("a", "b", "c"),
        [
            require("goal", "a", True),
            implies("first", "a", "b"),
            implies("second", "b", "c"),
            require("forbidden", "c", False),
        ],
    )
    report = diagnose(data)
    assert report["feasibility"] == "impossible_within_constraints"
    assert report["proof"]["satisfying_assignments"] == 0
    assert report["proof"]["assignments_checked"] == 8
    assert set(report["proof"]["constraint_ids"]) == {
        "goal", "first", "second", "forbidden"
    }
    assert report["proof"]["witness"] is None


def test_absent_current_dependency_is_blocked_not_impossible():
    data = reconnect_request()
    data["observations"] = [observe("reconnect", True), observe("persistence", False)]
    report = diagnose(data)
    assert report["feasibility"] == "blocked_current_state"
    assert report["completeness"] == "missing_prerequisites"
    assert report["proof"]["satisfying_assignments"] == 1
    assert report["proof"]["observed_compatible_assignments"] == 0
    missing = [f for f in report["findings"] if f["code"] == "missing_prerequisite"]
    assert any(f["variable"] == "persistence" for f in missing)


@pytest.mark.parametrize("explicit_null", [False, True])
def test_unknown_dependency_does_not_become_an_asserted_absence(explicit_null):
    data = reconnect_request()
    data["observations"] = [observe("reconnect", True)]
    if explicit_null:
        data["observations"].append(observe("persistence", None))
    report = diagnose(data)
    assert report["feasibility"] == "consistent_within_constraints"
    assert report["completeness"] == "indeterminate"
    assert any(
        f["code"] == "unobserved_prerequisite" and f["variable"] == "persistence"
        for f in report["findings"]
    )
    assert not any(f["code"] == "missing_prerequisite" for f in report["findings"])


def test_observed_required_dependencies_are_distinct_from_real_world_success():
    data = reconnect_request()
    data["observations"] = [observe("reconnect", True), observe("persistence", True)]
    report = diagnose(data)
    assert report["feasibility"] == "consistent_within_constraints"
    assert report["completeness"] == "known_requirements_present"
    assert report["limits"]["world_feasibility"] == "not_established"
    assert report["limits"]["sources"] == "caller_supplied_unverified"
    assert report["quality"] == "indeterminate"


def test_joint_observations_can_conflict_without_a_globally_forced_variable():
    # Neither variable is mandatory in every valid model. Their observed
    # combination still violates the implication.
    data = request(("a", "b"), [implies("dependency", "a", "b")])
    data["observations"] = [observe("a", True), observe("b", False)]
    report = diagnose(data)
    assert report["feasibility"] == "blocked_current_state"
    assert report["proof"]["satisfying_assignments"] == 3
    assert report["proof"]["observed_compatible_assignments"] == 0
    assert report["findings"]


def test_matched_global_requirement_does_not_hide_a_conditional_missing_dependency():
    data = request(("a", "b", "c"), [
        require("global-goal", "c", True),
        implies("conditional-dependency", "a", "b"),
    ])
    data["observations"] = [
        observe("a", True), observe("b", False), observe("c", True),
    ]
    report = diagnose(data)
    assert report["feasibility"] == "blocked_current_state"
    assert report["completeness"] == "indeterminate"
    assert report["proof"]["observed_compatible_assignments"] == 0
    assert not any(f["code"] == "missing_prerequisite" for f in report["findings"])


def test_negative_prerequisite_is_not_lost_as_a_false_value():
    data = request(("offline", "network"), [
        require("offline-goal", "offline", True),
        implies("privacy", "offline", "network", after_value=False),
    ])
    data["observations"] = [observe("offline", True), observe("network", True)]
    report = diagnose(data)
    assert report["feasibility"] == "blocked_current_state"
    assert any(
        f.get("variable") == "network" and f.get("expected") is False
        for f in report["findings"]
    )


@pytest.mark.parametrize("statuses,expected", [
    ([], "indeterminate"),
    (["pass"], "declared_criteria_pass"),
    (["pass", "pass"], "declared_criteria_pass"),
    (["unknown"], "indeterminate"),
    (["pass", "unknown"], "indeterminate"),
    (["fail"], "declared_criteria_fail"),
    (["fail", "unknown"], "declared_criteria_fail"),
])
def test_quality_is_separate_and_missing_criteria_are_unknown(statuses, expected):
    data = request(("works",), [require("goal", "works", True)])
    data["criteria"] = [
        {"id": f"criterion-{i}", "status": status, "source": f"fixture:criterion-{i}"}
        for i, status in enumerate(statuses)
    ]
    report = diagnose(data)
    assert report["quality"] == expected
    assert report["feasibility"] == "consistent_within_constraints"
    assert report["limits"]["sources"] == "caller_supplied_unverified"


def test_empty_boolean_domain_has_one_empty_assignment():
    report = diagnose(request((), []))
    assert report["feasibility"] == "consistent_within_constraints"
    assert report["proof"]["assignments_checked"] == 1
    assert report["proof"]["satisfying_assignments"] == 1
    assert report["proof"]["witness"] == {}
    assert report["quality"] == "indeterminate"


def oracle_models(data):
    """Deliberately simple external truth table for the supported grammar."""
    models = []
    for values in product((False, True), repeat=len(data["variables"])):
        assignment = dict(zip(data["variables"], values))
        accepted = True
        for item in data["constraints"]:
            if item["kind"] == "require":
                valid = assignment[item["variable"]] == item["value"]
            else:
                before, after = item["if"], item["then"]
                valid = (
                    assignment[before["variable"]] != before["value"]
                    or assignment[after["variable"]] == after["value"]
                )
            accepted = accepted and valid
        if accepted:
            models.append(assignment)
    return models


def oracle_cases():
    generator = random.Random(2718)
    pool = [require(f"r-{v}-{b}", v, b) for v in "abc" for b in (False, True)]
    pool += [
        implies(f"i-{a}-{b}-{x}-{y}", a, b, x, y)
        for a in "abc" for b in "abc" if a != b
        for x in (False, True) for y in (False, True)
    ]
    return [request(tuple("abc"), generator.sample(pool, generator.randrange(0, 9)))
            for _ in range(32)]


@pytest.mark.parametrize("data", oracle_cases())
def test_finite_model_results_match_independent_truth_table(data):
    models = oracle_models(data)
    report = diagnose(data)
    assert report["proof"]["satisfying_assignments"] == len(models)
    assert report["proof"]["assignments_checked"] == 8
    if models:
        assert report["feasibility"] == "consistent_within_constraints"
        assert report["proof"]["witness"] in models
    else:
        assert report["feasibility"] == "impossible_within_constraints"
        assert report["proof"]["witness"] is None


def test_order_does_not_change_the_verdict_or_model_count():
    data = reconnect_request()
    data["observations"] = [observe("persistence", False), observe("reconnect", True)]
    reordered = deepcopy(data)
    for field in ("variables", "constraints", "observations"):
        reordered[field].reverse()
    first, second = diagnose(data), diagnose(reordered)
    assert first["feasibility"] == second["feasibility"]
    assert first["completeness"] == second["completeness"]
    assert first["proof"]["satisfying_assignments"] == second["proof"]["satisfying_assignments"]
    # Reordering is still a different exact input snapshot.
    assert first["input_hash"] != second["input_hash"]


def test_over_budget_is_indeterminate_not_a_failed_search_proof():
    data = request(tuple(f"v{i}" for i in range(13)), [])
    report = diagnose(data)
    assert report["feasibility"] == "indeterminate"
    assert report["proof"] is None
    assert report["limits"]["actual_variables"] == 13
    assert report["next_checks"]


def test_smaller_caller_budget_is_respected():
    report = diagnose(reconnect_request(), max_variables=1)
    assert report["feasibility"] == "indeterminate"
    assert report["proof"] is None


@pytest.mark.parametrize("budget", [True, False, -1, 13, 1.0, "12", None])
def test_invalid_search_budgets_cannot_expand_the_verifier_domain(budget):
    with pytest.raises((ValueError, TypeError)):
        diagnose(reconnect_request(), max_variables=budget)


def test_unsupported_constraint_abstains_even_when_known_subset_looks_consistent():
    data = reconnect_request()
    data["constraints"].append({"id": "opaque", "kind": "future-solver", "source": "fixture:opaque"})
    report = diagnose(data)
    assert report["feasibility"] == "indeterminate"
    assert report["proof"] is None
    assert report["findings"]


@pytest.mark.parametrize("field,value", [
    ("schema", "parcimonia.feasibility-request/v99"),
    ("task_id", ""),
    ("scope_id", " padded "),
    ("revision", 42),
    ("variables", ["a", "a"]),
    ("variables", [True]),
    ("variables", "a"),
    ("constraints", {}),
    ("observations", {}),
    ("criteria", {}),
])
def test_invalid_contract_fields_are_rejected(field, value):
    data = request()
    data[field] = value
    with pytest.raises((ValueError, TypeError)):
        diagnose(data)


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_requirement_values_are_actual_booleans(value):
    data = request(("a",), [require("goal", "a", value)])
    with pytest.raises((ValueError, TypeError)):
        diagnose(data)


@pytest.mark.parametrize("value", [0, 1, "false"])
def test_observation_values_do_not_coerce_numbers_or_text(value):
    data = request(("a",), [])
    data["observations"] = [observe("a", value)]
    with pytest.raises((ValueError, TypeError)):
        diagnose(data)


def test_constraint_references_must_name_declared_variables():
    data = request(("a",), [implies("dependency", "a", "not-declared")])
    with pytest.raises((ValueError, TypeError)):
        diagnose(data)


def test_duplicate_constraint_ids_cannot_hide_distinct_claims():
    data = request(("a",), [require("same", "a", True), require("same", "a", False)])
    with pytest.raises((ValueError, TypeError)):
        diagnose(data)


def test_duplicate_observations_are_not_resolved_by_input_order():
    data = request(("a",), [])
    data["observations"] = [observe("a", True), observe("a", False)]
    with pytest.raises((ValueError, TypeError)):
        diagnose(data)


def test_stale_observation_cannot_fill_current_missing_evidence():
    data = reconnect_request()
    old = observe("persistence", True)
    old["revision"] = "fixture-old"
    data["observations"] = [old]
    with pytest.raises((ValueError, TypeError)):
        diagnose(data)


@pytest.mark.parametrize("where", ["request", "constraint", "observation", "criterion", "literal"])
def test_closed_schemas_reject_uninterpreted_fields(where):
    data = reconnect_request()
    data["observations"] = [observe("persistence", True)]
    data["criteria"] = [{"id": "test", "status": "pass", "source": "fixture:test"}]
    targets = {
        "request": data,
        "constraint": data["constraints"][0],
        "observation": data["observations"][0],
        "criterion": data["criteria"][0],
        "literal": data["constraints"][1]["if"],
    }
    targets[where]["unexpected"] = "must not be silently ignored"
    with pytest.raises((ValueError, TypeError)):
        diagnose(data)


def test_report_is_snapshot_bound_json_and_diagnosis_does_not_mutate_input():
    data = reconnect_request()
    original = deepcopy(data)
    report = diagnose(data)
    assert data == original
    assert report["input_hash"] == hash_input(data)
    assert report["schema"] == "parcimonia.feasibility-report/v1"
    assert report["mode"] == "shadow"
    assert report["limits"]["savings"] == "not_measured"
    assert "confidence" not in report
    assert json.loads(json.dumps(report, allow_nan=False)) == report
    assert diagnose(data) == report
    data["revision"] = "fixture-2"
    assert diagnose(data)["input_hash"] != report["input_hash"]


def report_registry():
    registry = VerifierRegistry()
    register_feasibility_verifier(registry)
    return registry


def test_registered_verifier_recomputes_report_and_binds_exact_input():
    data = reconnect_request()
    value = {"request": data, "report": diagnose(data)}
    verification = report_registry().verify("boolean-feasibility-report", "1", value)
    assert verification.verdict is True
    assert verification.input_hash == hash_input(value)


@pytest.mark.parametrize("tamper", ["verdict", "proof", "hash", "source", "extra-field", "budget", "bool-as-int"])
def test_verifier_refuses_tampered_results_and_inputs(tamper):
    data = reconnect_request()
    value = {"request": data, "report": diagnose(data)}
    if tamper == "verdict":
        value["report"]["feasibility"] = "impossible_within_constraints"
    elif tamper == "proof":
        value["report"]["proof"]["satisfying_assignments"] = 0
    elif tamper == "hash":
        value["report"]["input_hash"] = "0" * 64
    elif tamper == "source":
        value["request"]["constraints"][0]["source"] = "fixture:changed"
    elif tamper == "extra-field":
        value["report"]["approved"] = True
    elif tamper == "budget":
        value["report"]["limits"]["max_variables"] = 100
    else:
        # Python considers True == 1; canonical JSON must keep them distinct.
        value["report"]["proof"]["witness"]["reconnect"] = 1
    assert report_registry().verify("boolean-feasibility-report", "1", value).verdict is not True


def test_optional_empty_lists_do_not_change_the_behavior():
    data = reconnect_request()
    explicit = diagnose(data)
    del data["observations"]
    del data["criteria"]
    implicit = diagnose(data)
    assert explicit["feasibility"] == implicit["feasibility"]
    assert explicit["quality"] == implicit["quality"]
    assert explicit["completeness"] == implicit["completeness"]
    assert explicit["input_hash"] != implicit["input_hash"]
