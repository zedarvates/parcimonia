"""Iterative 2-SAT solving with directly checkable witnesses or contradictions.

The solver proves satisfiability of a supplied finite formula, not the truth
of its source assumptions or feasibility in the outside world. No route runs.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from .verification import hash_input

FORMULA_SCHEMA = "parcimonia.2cnf/v1"
RESULT_SCHEMA = "parcimonia.2sat-result/v1"
ENGINE = {"id": "implication-graph-2sat", "version": "1"}
MAX_VARIABLES = 128
MAX_CLAUSES = 384

__all__ = [
    "solve_2cnf",
    "verify_2cnf_assignment",
    "verify_2sat_result",
]


def _object(value: Any, fields: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{label} must contain exactly {sorted(fields)}.")


def _literal(value: Any, count: int) -> bool:
    return type(value) is int and 1 <= abs(value) <= count


def _validate_formula(formula: Any) -> None:
    _object(formula, {"schema", "variables", "clauses"}, "formula")
    if type(formula["schema"]) is not str or formula["schema"] != FORMULA_SCHEMA:
        raise ValueError("Unsupported 2-CNF schema.")
    variables = formula["variables"]
    if type(variables) is not list or len(variables) > MAX_VARIABLES:
        raise ValueError(f"variables must be an array of at most {MAX_VARIABLES} names.")
    for variable in variables:
        if (
            type(variable) is not str
            or not variable
            or variable != variable.strip()
            or len(variable) > 4096
        ):
            raise ValueError("Variable names must be trimmed strings of 1..4096 characters.")
    if len(set(variables)) != len(variables):
        raise ValueError("Variable names must be unique.")
    clauses = formula["clauses"]
    if type(clauses) is not list or len(clauses) > MAX_CLAUSES:
        raise ValueError(f"clauses must be an array of at most {MAX_CLAUSES} clauses.")
    for clause in clauses:
        if type(clause) is not list or len(clause) not in (1, 2):
            raise ValueError("Each 2-CNF clause must contain one or two literals.")
        if not all(_literal(value, len(variables)) for value in clause):
            raise ValueError("Literal IDs must be nonzero signed integers within the variable domain.")
    try:
        hash_input(formula)
    except UnicodeError as exc:
        raise ValueError("Formula text must be valid UTF-8.") from exc


def _assignment_matches(formula: dict[str, Any], assignment: Any) -> bool:
    if type(assignment) is not dict or set(assignment) != set(formula["variables"]):
        return False
    if any(type(key) is not str or type(value) is not bool for key, value in assignment.items()):
        return False
    values = [assignment[name] for name in formula["variables"]]
    return all(
        any(values[abs(literal) - 1] is (literal > 0) for literal in clause)
        for clause in formula["clauses"]
    )


def verify_2cnf_assignment(formula: Any, assignment: Any) -> bool:
    """Check a complete Boolean assignment directly, without solving.

    Malformed formulas or assignments return False. Indices preserve the
    formula's declared variable order; no coercion or partial assignment is used.
    """
    try:
        _validate_formula(formula)
        return _assignment_matches(formula, assignment)
    except (TypeError, ValueError):
        return False


def _graphs(formula: dict[str, Any]) -> tuple[dict[int, list[tuple[int, int]]], dict[int, list[int]]]:
    literals = [value for index in range(1, len(formula["variables"]) + 1) for value in (index, -index)]
    graph: dict[int, list[tuple[int, int]]] = {literal: [] for literal in literals}
    reverse: dict[int, list[int]] = {literal: [] for literal in literals}
    for clause_index, clause in enumerate(formula["clauses"]):
        first = clause[0]
        edges = [(-first, first)] if len(clause) == 1 else [(-first, clause[1]), (-clause[1], first)]
        for source, target in edges:
            graph[source].append((target, clause_index))
            reverse[target].append(source)
    return graph, reverse


def _components(
    graph: dict[int, list[tuple[int, int]]], reverse: dict[int, list[int]]
) -> dict[int, int]:
    """Kosaraju's two graph passes, with explicit stacks instead of recursion."""
    visited: set[int] = set()
    finish: list[int] = []
    for start in graph:
        if start in visited:
            continue
        visited.add(start)
        pending = [(start, 0)]
        while pending:
            node, offset = pending[-1]
            if offset == len(graph[node]):
                pending.pop()
                finish.append(node)
                continue
            pending[-1] = (node, offset + 1)
            target = graph[node][offset][0]
            if target not in visited:
                visited.add(target)
                pending.append((target, 0))
    components: dict[int, int] = {}
    component_id = 0
    for start in reversed(finish):
        if start in components:
            continue
        components[start] = component_id
        pending = [start]
        while pending:
            node = pending.pop()
            for target in reverse[node]:
                if target not in components:
                    components[target] = component_id
                    pending.append(target)
        component_id += 1
    return components


def _path(
    graph: dict[int, list[tuple[int, int]]], components: dict[int, int], start: int, end: int
) -> dict[str, list[int]]:
    """Find a bounded path inside one component, retaining clause attribution."""
    pending = deque([start])
    parents: dict[int, tuple[int, int] | None] = {start: None}
    while pending and end not in parents:
        node = pending.popleft()
        for target, clause_index in graph[node]:
            if target not in parents and components[target] == components[start]:
                parents[target] = (node, clause_index)
                pending.append(target)
    if end not in parents:
        raise RuntimeError("SCC members must have a connecting path.")
    literals = [end]
    clause_indices = []
    node = end
    while node != start:
        parent = parents[node]
        if parent is None:
            raise RuntimeError("Incomplete implication path.")
        node, clause_index = parent
        literals.append(node)
        clause_indices.append(clause_index)
    return {"literals": list(reversed(literals)), "clause_indices": list(reversed(clause_indices))}


def solve_2cnf(formula: dict[str, Any]) -> dict[str, Any]:
    """Solve a supported 2-CNF formula in graph-linear work after validation.

    A satisfiable result contains a directly checked complete assignment. An
    unsatisfiable result contains both directions of a contradictory implication
    cycle, independently checkable against the indexed source clauses.
    """
    _validate_formula(formula)
    graph, reverse = _graphs(formula)
    components = _components(graph, reverse)
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "engine": dict(ENGINE),
        "input_hash": hash_input(formula),
        "status": "satisfiable",
        "assignment": None,
        "certificate": None,
    }
    for index, variable in enumerate(formula["variables"], start=1):
        if components[index] == components[-index]:
            result["status"] = "unsatisfiable"
            result["certificate"] = {
                "kind": "contradictory_implication_paths",
                "variable": variable,
                "positive_to_negative": _path(graph, components, index, -index),
                "negative_to_positive": _path(graph, components, -index, index),
            }
            if not verify_2sat_result(formula, result):
                raise RuntimeError("Generated contradiction certificate did not verify.")
            return result
    assignment = {
        variable: components[index] > components[-index]
        for index, variable in enumerate(formula["variables"], start=1)
    }
    if not _assignment_matches(formula, assignment):
        raise RuntimeError("Generated assignment did not satisfy the formula.")
    result["assignment"] = assignment
    result["certificate"] = {"kind": "satisfying_assignment"}
    return result


def _check_path(formula: dict[str, Any], path: Any, start: int, end: int) -> bool:
    _object(path, {"literals", "clause_indices"}, "implication path")
    literals, indices = path["literals"], path["clause_indices"]
    count = len(formula["variables"])
    if type(literals) is not list or not 2 <= len(literals) <= 2 * count:
        return False
    if not all(_literal(value, count) for value in literals):
        return False
    if literals[0] != start or literals[-1] != end:
        return False
    if type(indices) is not list or len(indices) != len(literals) - 1:
        return False
    for source, target, index in zip(literals, literals[1:], indices):
        if type(index) is not int or not 0 <= index < len(formula["clauses"]):
            return False
        clause = formula["clauses"][index]
        first = clause[0]
        if len(clause) == 1:
            justified = source == -first and target == first
        else:
            second = clause[1]
            justified = (source == -first and target == second) or (source == -second and target == first)
        if not justified:
            return False
    return True


def verify_2sat_result(formula: Any, result: Any) -> bool:
    """Verify a SAT witness or UNSAT proof without running the SCC solver.

    Valid alternative witnesses or paths are accepted; this verifies the claim,
    not byte identity with the solver's deterministic preferred output.
    """
    try:
        _validate_formula(formula)
        _object(result, {"schema", "engine", "input_hash", "status", "assignment", "certificate"}, "result")
        if type(result["schema"]) is not str or result["schema"] != RESULT_SCHEMA:
            return False
        _object(result["engine"], {"id", "version"}, "engine")
        if any(
            type(result["engine"][key]) is not str or result["engine"][key] != value
            for key, value in ENGINE.items()
        ):
            return False
        if type(result["input_hash"]) is not str or result["input_hash"] != hash_input(formula):
            return False
        certificate = result["certificate"]
        if type(result["status"]) is not str:
            return False
        if result["status"] == "satisfiable":
            _object(certificate, {"kind"}, "SAT certificate")
            return (
                type(certificate["kind"]) is str
                and certificate["kind"] == "satisfying_assignment"
                and _assignment_matches(formula, result["assignment"])
            )
        if result["status"] != "unsatisfiable" or result["assignment"] is not None:
            return False
        _object(
            certificate,
            {"kind", "variable", "positive_to_negative", "negative_to_positive"},
            "UNSAT certificate",
        )
        if type(certificate["kind"]) is not str or certificate["kind"] != "contradictory_implication_paths":
            return False
        variable = certificate["variable"]
        if type(variable) is not str or variable not in formula["variables"]:
            return False
        index = formula["variables"].index(variable) + 1
        return _check_path(
            formula, certificate["positive_to_negative"], index, -index
        ) and _check_path(
            formula, certificate["negative_to_positive"], -index, index
        )
    except (TypeError, ValueError):
        return False
