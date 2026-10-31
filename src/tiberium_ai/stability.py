"""Bounded, advisory Python stability-pattern inspection without execution.

A finding identifies syntax worth investigating. It does not demonstrate an
unstable execution, and a clean report does not establish stability.
"""

from __future__ import annotations

import ast
import math
from typing import Any

from .verification import hash_input

__all__ = ["inspect_python_stability"]

_MAX_SOURCE_BYTES = 256 * 1024
_MAX_AST_NODES = 10_000
_MAX_AST_DEPTH = 128
_RULES = (
    "mutable_default_argument",
    "single_threshold_switch",
    "retry_without_visible_exit",
)


def inspect_python_stability(
    source: str, *, source_id: str, revision: str
) -> dict[str, Any]:
    """Inspect three supported syntax patterns in caller-supplied Python text.

    No source is imported or executed. Sources outside the byte/AST budgets or
    those that do not parse produce an indeterminate report. Identifiers are
    caller declarations and are not authenticated file or revision identities.
    """
    if not isinstance(source, str):
        raise ValueError("source must be a string.")
    for name, value in (("source_id", source_id), ("revision", revision)):
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 256
        ):
            raise ValueError(
                f"{name} must be a nonempty trimmed string of at most 256 characters."
            )
    try:
        source_bytes = len(source.encode("utf-8"))
        input_hash = hash_input(
            {"source": source, "source_id": source_id, "revision": revision}
        )
    except UnicodeError as exc:
        raise ValueError("source and identifiers must be valid UTF-8 text.") from exc
    report: dict[str, Any] = {
        "schema": "parcimonia.stability-report/v1",
        "source_id": source_id,
        "revision": revision,
        "input_hash": input_hash,
        "engine": {"id": "python-stability-patterns", "version": "1"},
        "mode": "shadow",
        "status": "indeterminate",
        "findings": [],
        "reason_codes": [],
        "limits": {
            "analysis": "static_syntax_only",
            "grammar": "python3.10",
            "stability": "not_established",
            "absence_of_other_risks": "not_established",
            "sources": "caller_supplied_unverified",
            "max_source_bytes": _MAX_SOURCE_BYTES,
            "source_bytes": source_bytes,
            "max_ast_nodes": _MAX_AST_NODES,
            "max_ast_depth": _MAX_AST_DEPTH,
            "ast_nodes": None,
            "supported_rules": list(_RULES),
        },
    }
    if source_bytes > _MAX_SOURCE_BYTES:
        report["reason_codes"] = ["source_byte_budget_exceeded"]
        return report
    try:
        tree = ast.parse(source, feature_version=(3, 10))
    except (SyntaxError, ValueError):
        report["reason_codes"] = ["source_syntax_invalid"]
        return report
    except (RecursionError, MemoryError):
        report["reason_codes"] = ["parser_resource_limit"]
        return report

    nodes: list[ast.AST] = []
    pending = [(tree, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > _MAX_AST_DEPTH:
            report["reason_codes"] = ["ast_depth_budget_exceeded"]
            return report
        nodes.append(node)
        if len(nodes) > _MAX_AST_NODES:
            report["reason_codes"] = ["ast_node_budget_exceeded"]
            return report
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    report["limits"]["ast_nodes"] = len(nodes)

    findings = []
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    findings.append(
                        _finding(
                            "mutable_default_argument",
                            default,
                            "A literal mutable default can share state across calls; "
                            "this can make results depend on call order.",
                            "Call the function repeatedly in different orders and check "
                            "whether each invocation receives the intended fresh state.",
                        )
                    )
        elif isinstance(node, ast.If) and _single_threshold_switch(node):
            findings.append(
                _finding(
                    "single_threshold_switch",
                    node,
                    "Two constant states switch at one numeric threshold. Input noise "
                    "could cause oscillation; this local shape shows no hysteresis.",
                    "Replay inputs just above and below the threshold; compare the "
                    "observed transitions with explicit hysteresis or debounce criteria.",
                )
            )
        elif isinstance(node, ast.While) and _retry_without_visible_exit(node):
            findings.append(
                _finding(
                    "retry_without_visible_exit",
                    node,
                    "A literal while-True loop catches exceptions with no local "
                    "break, return or raise visible. Retry termination is not established; "
                    "called helpers or external cancellation may still stop it.",
                    "Run a bounded failure scenario and verify attempt/deadline limits "
                    "and cancellation, including behavior of called helpers.",
                )
            )
    report["findings"] = sorted(
        findings, key=lambda item: (item["line"], item["end_line"], item["rule_id"])
    )
    report["status"] = (
        "risks_identified" if findings else "no_supported_pattern_found"
    )
    return report


def _finding(
    rule_id: str, node: ast.AST, explanation: str, next_check: str
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "line": node.lineno,
        "end_line": node.end_lineno,
        "explanation": explanation,
        "next_check": next_check,
        "verdict": "risk_indicator",
    }


def _reference(node: ast.AST) -> bool:
    """Accept only names and attribute chains, without evaluating attributes."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _number(node: ast.AST) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        node = node.operand
    if not isinstance(node, ast.Constant) or type(node.value) not in (int, float):
        return False
    return type(node.value) is int or math.isfinite(node.value)


def _single_threshold_switch(node: ast.If) -> bool:
    test = node.test
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], (ast.Lt, ast.LtE, ast.Gt, ast.GtE))
        or len(test.comparators) != 1
        or len(node.body) != 1
        or len(node.orelse) != 1
    ):
        return False
    right = test.comparators[0]
    if not (
        (_reference(test.left) and _number(right))
        or (_number(test.left) and _reference(right))
    ):
        return False
    first, second = node.body[0], node.orelse[0]
    if not isinstance(first, ast.Assign) or not isinstance(second, ast.Assign):
        return False
    if len(first.targets) != 1 or len(second.targets) != 1:
        return False
    if not _reference(first.targets[0]) or not _reference(second.targets[0]):
        return False
    if ast.dump(first.targets[0]) != ast.dump(second.targets[0]):
        return False
    if not isinstance(first.value, ast.Constant) or not isinstance(
        second.value, ast.Constant
    ):
        return False
    left_value, right_value = first.value.value, second.value.value
    return (
        type(left_value) is type(right_value)
        and type(left_value) in (bool, int, float, str, type(None))
        and left_value != right_value
    )


def _retry_without_visible_exit(node: ast.While) -> bool:
    if not (
        isinstance(node.test, ast.Constant)
        and node.test.value is True
        and not node.orelse
    ):
        return False
    has_handler = False
    pending: list[ast.AST] = list(node.body)
    while pending:
        child = pending.pop()
        if isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        # Nested loops complicate which exits apply: defer instead of guessing.
        if isinstance(child, (ast.While, ast.For, ast.AsyncFor)):
            return False
        if isinstance(child, (ast.Break, ast.Return, ast.Raise)):
            return False
        if isinstance(child, ast.Try) and child.handlers:
            has_handler = True
        pending.extend(ast.iter_child_nodes(child))
    return has_handler
