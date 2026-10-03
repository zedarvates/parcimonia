"""Paired descriptive comparison of advisory Tev1 captures, without inference."""

from __future__ import annotations

import math
from collections import Counter
from statistics import median
from typing import Any

from .measurement import Environment
from .reflex import ReflexKind
from .tev1_cases import agrees, corpus_revision, rule_baseline, tev1_cases
from .tev1_transport import Tev1Identity


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _validate(report: Any, model: str) -> None:
    if (
        not isinstance(report, dict)
        or type(report.get("schema_version")) is not int
        or report["schema_version"] != 1
    ):
        raise ValueError("invalid_pair_report")
    if (
        report.get("corpus_revision") != corpus_revision()
        or report.get("label_origin") != "fixture"
    ):
        raise ValueError("pair_corpus_mismatch")
    if (
        report.get("auto_act_allowed") is not False
        or report.get("saving_claim") is not False
    ):
        raise ValueError("pair_is_not_advisory")
    if report.get("capture_origin") not in ("fixture", "recorded"):
        raise ValueError("invalid_pair_origin")
    identity_data = report.get("identity")
    if not isinstance(identity_data, dict) or set(identity_data) != {
        "model",
        "model_digest",
        "ollama_version",
    }:
        raise ValueError("invalid_pair_identity")
    identity = Tev1Identity(**identity_data)
    if identity.model != model:
        raise ValueError("pair_model_role_mismatch")
    budget = report.get("budget_ms")
    if not _finite(budget) or not 0 < budget <= 120000:
        raise ValueError("invalid_pair_budget")
    environment = report.get("environment")
    if environment is not None:
        if not isinstance(environment, dict) or set(environment) != {
            "machine_id",
            "runtime_versions",
        }:
            raise ValueError("invalid_pair_environment")
        Environment(**environment)
        if environment["runtime_versions"].get("ollama") != identity.ollama_version:
            raise ValueError("pair_environment_runtime_mismatch")
    cases = tev1_cases()
    rows = report.get("cases")
    if (
        not isinstance(rows, list)
        or len(rows) != len(cases)
        or type(report.get("attempted")) is not int
        or report["attempted"] != len(cases)
    ):
        raise ValueError("pair_cases_missing")
    for case, row in zip(cases, rows):
        if (
            not isinstance(row, dict)
            or row.get("case_id") != case.case_id
            or row.get("family") != case.family
        ):
            raise ValueError("pair_case_order_mismatch")
        if (
            type(row.get("expected")) is not type(case.expected)
            or row["expected"] != case.expected
            or row.get("rules") != rule_baseline(case)
        ):
            raise ValueError("pair_label_mismatch")
        observed = row.get("model")
        status = row.get("status")
        if status not in ("ok", "unusable", "unavailable", "error") or (
            status == "ok"
        ) != (observed is not None):
            raise ValueError("pair_status_mismatch")
        if observed is not None:
            if case.question.kind == ReflexKind.CHOICE:
                valid = (
                    isinstance(observed, str) and observed in case.question.option_keys
                )
            elif case.question.kind == ReflexKind.NOUL:
                valid = type(observed) is bool
            else:
                valid = (
                    _finite(observed) and observed <= len(case.question.option_keys) - 1
                )
            if not valid:
                raise ValueError("invalid_pair_answer")
        if not _finite(row.get("attempt_latency_ms")):
            raise ValueError("invalid_pair_latency")
    resources = report.get("resources")
    if not isinstance(resources, dict):
        raise TypeError("invalid_pair_resources")
    for key in ("input_tokens", "output_tokens"):
        value = resources.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("invalid_pair_resources")


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    rows = report["cases"]
    cases = tev1_cases()
    correct = sum(agrees(case, row["model"]) for case, row in zip(cases, rows))
    answered = sum(row["model"] is not None for row in rows)
    latencies = [row["attempt_latency_ms"] for row in rows]
    return {
        "identity": report["identity"],
        "environment": report.get("environment"),
        "attempted": len(rows),
        "answered_usable": answered,
        "correct": correct,
        "coverage": answered / len(rows),
        "agreement_all_cases": correct / len(rows),
        "agreement_answered": correct / answered if answered else None,
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "latency_ms": {
            "first_attempt": latencies[0],
            "median_all_attempts": median(latencies),
            "p95_all_attempts": sorted(latencies)[math.ceil(0.95 * len(latencies)) - 1],
            "median_after_first_attempt": median(latencies[1:]),
        },
        "resources": {
            "input_tokens": report["resources"].get("input_tokens"),
            "output_tokens": report["resources"].get("output_tokens"),
            "vram_bytes": None,
            "energy_joules": None,
            "cost": None,
            "downstream_and_fallback_cost": None,
        },
    }


def compare_tev1_runs(small: dict[str, Any], large: dict[str, Any]) -> dict[str, Any]:
    """Compare exactly the same authored cases; never choose an active model.

    The CLI reconstructs these reports from pinned records, rather than trusting
    precomputed comparison.json totals. Timing deltas require matching declared
    environments. Such a label still does not attest to GPU state or isolation.
    """
    _validate(small, "tev1:0.8b")
    _validate(large, "tev1:4b")
    if small["budget_ms"] != large["budget_ms"]:
        raise ValueError("pair_budget_mismatch")
    if small["identity"]["ollama_version"] != large["identity"]["ollama_version"]:
        raise ValueError("pair_runtime_mismatch")
    if small["identity"]["model_digest"] == large["identity"]["model_digest"]:
        raise ValueError("pair_models_share_digest")
    if small["capture_origin"] != large["capture_origin"]:
        raise ValueError("pair_origin_mismatch")
    environments = (small.get("environment"), large.get("environment"))
    if (
        all(environment is not None for environment in environments)
        and environments[0] != environments[1]
    ):
        raise ValueError("pair_environment_mismatch")
    matched_environment = all(environment is not None for environment in environments)
    rows = []
    outcomes = Counter(
        {
            "both_correct": 0,
            "small_only_correct": 0,
            "large_only_correct": 0,
            "neither_correct": 0,
        }
    )
    families = {}
    for case, s, l in zip(tev1_cases(), small["cases"], large["cases"]):
        s_correct, l_correct = agrees(case, s["model"]), agrees(case, l["model"])
        outcome = (
            "both_correct"
            if s_correct and l_correct
            else "small_only_correct"
            if s_correct
            else "large_only_correct"
            if l_correct
            else "neither_correct"
        )
        outcomes[outcome] += 1
        paired_usable = s["model"] is not None and l["model"] is not None
        rows.append(
            {
                "case_id": case.case_id,
                "family": case.family,
                "expected": case.expected,
                "rules": rule_baseline(case),
                "small": {
                    "observed": s["model"],
                    "correct": s_correct,
                    "status": s["status"],
                    "attempt_latency_ms": s["attempt_latency_ms"],
                },
                "large": {
                    "observed": l["model"],
                    "correct": l_correct,
                    "status": l["status"],
                    "attempt_latency_ms": l["attempt_latency_ms"],
                },
                "quality_outcome": outcome,
                "large_minus_small_latency_ms": l["attempt_latency_ms"]
                - s["attempt_latency_ms"]
                if matched_environment and paired_usable
                else None,
            }
        )
        family = families.setdefault(
            case.family,
            {
                "attempted": 0,
                "rules_correct": 0,
                "small_correct": 0,
                "large_correct": 0,
                "small_answered_usable": 0,
                "large_answered_usable": 0,
            },
        )
        family["attempted"] += 1
        family["rules_correct"] += agrees(case, rule_baseline(case))
        family["small_correct"] += s_correct
        family["large_correct"] += l_correct
        family["small_answered_usable"] += s["model"] is not None
        family["large_answered_usable"] += l["model"] is not None
    return {
        "kind": "tev1_paired_comparison",
        "schema_version": 1,
        "corpus_revision": corpus_revision(),
        "label_origin": "fixture",
        "capture_origin": small["capture_origin"],
        "budget_ms": small["budget_ms"],
        "attempted_per_model": len(rows),
        "environment_relation": "same_declared" if matched_environment else "unknown",
        "latency_scope": "wall_clock_attempt_including_identity_checks",
        "load_state": "unobserved",
        "percentile_method": "nearest_rank",
        "small": _summary(small),
        "large": _summary(large),
        "paired_quality_counts": dict(outcomes),
        "by_family": families,
        "cases": rows,
        "selected_model": None,
        "auto_act_allowed": False,
        "saving_claim": False,
        "total_cost_comparison": "unavailable",
    }
