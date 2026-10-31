"""Independent truth tables and proof tampering at the 2-SAT boundary."""

from copy import deepcopy
from itertools import combinations_with_replacement, product

import pytest

from tiberium_ai.two_sat import (
    solve_2cnf,
    verify_2cnf_assignment,
    verify_2sat_result,
)
from tiberium_ai.verification import hash_input


def formula(variables=("a", "b"), clauses=()):
    return {
        "schema": "parcimonia.2cnf/v1",
        "variables": list(variables),
        "clauses": [list(clause) for clause in clauses],
    }


def _oracle(data):
    # Evaluate signed disjunctions, independent of graph edges and SCC ordering.
    for values in product((False, True), repeat=len(data["variables"])):
        if all(any(values[abs(value) - 1] == (value > 0) for value in clause) for clause in data["clauses"]):
            return dict(zip(data["variables"], values))
    return None


def test_all_two_variable_formulas_through_three_clauses_match_truth_tables():
    literals = (-2, -1, 1, 2)
    clauses = [(value,) for value in literals] + list(combinations_with_replacement(literals, 2))
    checked = 0
    for size in range(4):
        for selection in combinations_with_replacement(clauses, size):
            data = formula(clauses=selection)
            expected = _oracle(data)
            result = solve_2cnf(data)
            assert (result["status"] == "satisfiable") == (expected is not None), data
            assert verify_2sat_result(data, result), data
            if expected is None:
                assert result["assignment"] is None
                assert result["certificate"]["kind"] == "contradictory_implication_paths"
            else:
                assert verify_2cnf_assignment(data, result["assignment"])
            checked += 1
    assert checked == 680


@pytest.mark.parametrize("clauses,expected", [
    ([[1]], True), ([[-1]], True), ([[1], [-1]], False),
    ([[1, -1]], True), ([[1, 1], [-1, -1]], False),
    ([[1], [-1, 2], [-2]], False),
    ([[-1, 2], [-2, -1], [1]], False),
    ([[1, 2], [-1, 2], [1, -2], [-1, -2]], False),
])
def test_polarities_units_tautologies_and_binary_contradictions(clauses, expected):
    data = formula(clauses=clauses)
    result = solve_2cnf(data)
    assert (result["status"] == "satisfiable") is expected
    assert verify_2sat_result(data, result)


def test_no_variables_and_no_clauses_have_an_empty_witness():
    data = formula((), ())
    result = solve_2cnf(data)
    assert result["assignment"] == {}
    assert result["status"] == "satisfiable"
    assert verify_2sat_result(data, result)


def test_literal_indices_keep_declared_variable_order():
    data = formula(("second", "first"), [[1], [-2]])
    result = solve_2cnf(data)
    assert result["assignment"] == {"second": True, "first": False}
    assert not verify_2cnf_assignment(data, {"first": True, "second": False})


def test_128_variable_chain_uses_no_truth_table_or_recursive_search():
    names = [f"v{index}" for index in range(1, 129)]
    clauses = [[1]] + [[-index, index + 1] for index in range(1, 128)]
    data = formula(names, clauses)
    result = solve_2cnf(data)
    assert result["status"] == "satisfiable"
    assert result["assignment"] == dict.fromkeys(names, True)
    assert verify_2sat_result(data, result)
    data["clauses"].append([-128])
    contradictory = solve_2cnf(data)
    assert contradictory["status"] == "unsatisfiable"
    assert verify_2sat_result(data, contradictory)
    path = contradictory["certificate"]["positive_to_negative"]
    assert len(path["literals"]) == 256


def test_maximum_clause_count_is_supported_and_no_input_is_mutated():
    data = formula(clauses=[[1, -1]] * 384)
    before = deepcopy(data)
    first = solve_2cnf(data)
    second = solve_2cnf(data)
    assert first == second
    assert data == before
    assert first["input_hash"] == hash_input(data)
    assert verify_2sat_result(data, first)


@pytest.mark.parametrize("change", [
    lambda d: d.update(extra=True),
    lambda d: d.update(schema="other"),
    lambda d: d.update(variables=("a", "b")),
    lambda d: d.update(variables=["a", "a"]),
    lambda d: d.update(variables=[""]),
    lambda d: d.update(variables=[" a"]),
    lambda d: d.update(variables=[True]),
    lambda d: d.update(variables=["x" * 4097]),
    lambda d: d.update(variables=["\ud800"]),
    lambda d: d.update(variables=[f"v{i}" for i in range(129)]),
    lambda d: d.update(clauses=[[1]] * 385),
    lambda d: d.update(clauses=([1],)),
    lambda d: d.update(clauses=[()]),
    lambda d: d.update(clauses=[[]]),
    lambda d: d.update(clauses=[[1, 2, -1]]),
    lambda d: d.update(clauses=[[0]]),
    lambda d: d.update(clauses=[[True]]),
    lambda d: d.update(clauses=[[False]]),
    lambda d: d.update(clauses=[[1.0]]),
    lambda d: d.update(clauses=[["1"]]),
    lambda d: d.update(clauses=[[3]]),
    lambda d: d.update(clauses=[[-3]]),
    lambda d: d.update(variables=[], clauses=[[1]]),
])
def test_invalid_formula_cannot_be_solved_or_verified(change):
    data = formula()
    change(data)
    with pytest.raises(ValueError):
        solve_2cnf(data)
    assert verify_2cnf_assignment(data, {}) is False
    assert verify_2sat_result(data, {}) is False


@pytest.mark.parametrize("assignment", [
    None, [], {}, {"a": True}, {"a": True, "b": False, "extra": True},
    {"a": 1, "b": False}, {"a": True, "b": 0}, {"a": True, "b": "false"},
    {"a": False, "b": False},
])
def test_sat_verification_requires_a_complete_real_boolean_witness(assignment):
    data = formula(clauses=[[1]])
    assert not verify_2cnf_assignment(data, assignment)
    report = solve_2cnf(data)
    report["assignment"] = assignment
    assert not verify_2sat_result(data, report)


def test_any_valid_alternative_assignment_is_accepted_without_replaying_solver():
    data = formula(clauses=[[1, 2]])
    report = solve_2cnf(data)
    report["assignment"] = {"a": True, "b": False}
    assert verify_2sat_result(data, report)
    report["assignment"] = {"a": False, "b": True}
    assert verify_2sat_result(data, report)


@pytest.mark.parametrize("change", [
    lambda r: r.update(schema="other"),
    lambda r: r.update(extra=True),
    lambda r: r.update(input_hash="0" * 64),
    lambda r: r["engine"].update(version=1),
    lambda r: r["engine"].update(id="other"),
    lambda r: r["engine"].update(extra=True),
    lambda r: r.update(status=True),
    lambda r: r.update(status="unknown"),
    lambda r: r["certificate"].update(kind="other"),
    lambda r: r["certificate"].update(extra=True),
])
def test_report_identity_and_closed_contract_are_checked(change):
    data = formula(clauses=[[1]])
    report = solve_2cnf(data)
    change(report)
    assert not verify_2sat_result(data, report)


@pytest.mark.parametrize("change", [
    lambda r: r.update(assignment={}),
    lambda r: r.update(status="satisfiable"),
    lambda r: r["certificate"].update(variable="unknown"),
    lambda r: r["certificate"].update(variable="b"),
    lambda r: r["certificate"].pop("negative_to_positive"),
    lambda r: r["certificate"]["positive_to_negative"].update(literals=[]),
    lambda r: r["certificate"]["positive_to_negative"].update(literals=[1]),
    lambda r: r["certificate"]["positive_to_negative"].update(literals=[-1, 1]),
    lambda r: r["certificate"]["positive_to_negative"].update(clause_indices=[]),
    lambda r: r["certificate"]["positive_to_negative"].update(clause_indices=[True]),
    lambda r: r["certificate"]["positive_to_negative"].update(clause_indices=[-1]),
    lambda r: r["certificate"]["positive_to_negative"].update(clause_indices=[2]),
    lambda r: r["certificate"]["positive_to_negative"].update(literals=[True, -1]),
    lambda r: r["certificate"]["positive_to_negative"].update(literals=[0, -1]),
    lambda r: r["certificate"]["positive_to_negative"].update(literals=[1, -3]),
    lambda r: r["certificate"]["positive_to_negative"].update(extra=True),
])
def test_forged_unsat_paths_are_rejected(change):
    data = formula(clauses=[[1], [-1]])
    report = solve_2cnf(data)
    assert verify_2sat_result(data, report)
    change(report)
    assert not verify_2sat_result(data, report)


def test_implication_edges_cannot_be_reversed_or_attributed_to_wrong_clauses():
    data = formula(clauses=[[1], [-1]])
    report = solve_2cnf(data)
    assert report["certificate"]["positive_to_negative"] == {"literals": [1, -1], "clause_indices": [1]}
    assert report["certificate"]["negative_to_positive"] == {"literals": [-1, 1], "clause_indices": [0]}
    report["certificate"]["positive_to_negative"]["clause_indices"] = [0]
    assert not verify_2sat_result(data, report)


def test_formula_binding_rejects_certificate_from_another_instance():
    first = formula(clauses=[[1], [-1]])
    second = formula(clauses=[[1, 2]])
    report = solve_2cnf(first)
    assert not verify_2sat_result(second, report)
    report["input_hash"] = hash_input(second)
    assert not verify_2sat_result(second, report)


def test_binary_only_unsatisfiable_certificate_is_justified_by_each_binary_clause():
    data = formula(clauses=[[1, 2], [-1, 2], [1, -2], [-1, -2]])
    report = solve_2cnf(data)
    assert verify_2sat_result(data, report)
    certificate = report["certificate"]
    for key in ("positive_to_negative", "negative_to_positive"):
        path = certificate[key]
        assert len(path["literals"]) == 3
        for source, target, index in zip(path["literals"], path["literals"][1:], path["clause_indices"]):
            clause = data["clauses"][index]
            assert (source == -clause[0] and target == clause[1]) or (source == -clause[1] and target == clause[0])


def test_verification_does_not_invoke_the_solver(monkeypatch):
    data = formula(clauses=[[1], [-1]])
    report = solve_2cnf(data)

    def forbidden(*args, **kwargs):
        raise AssertionError("Proof verification must not solve again")

    monkeypatch.setattr("tiberium_ai.two_sat.solve_2cnf", forbidden)
    assert verify_2sat_result(data, report)


def test_verification_does_not_modify_formula_or_result():
    data = formula(clauses=[[1], [-1]])
    report = solve_2cnf(data)
    before = deepcopy((data, report))
    assert verify_2sat_result(data, report)
    assert (data, report) == before
