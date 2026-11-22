"""Advisory compute selection from fresh resources and workload-bound evidence.

Self-contained so a plugin can vendor this file without importing the whole
package. Reports supplied by callers remain host reports, never authorization.
"""
from __future__ import annotations

import math
import time

GIB = 1024 ** 3
TASKS = ("json_minify", "log_runs", "log_compact", "python_syntax", "text_generation", "embedding", "vision")
DEVICES = ("cpu", "gpu", "npu", "cloud")


def number(value, name, *, integer=False, optional=False):
    if optional and value is None:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value)) or not 0 <= value <= 10 ** 18
            or (integer and not isinstance(value, int))):
        raise ValueError(f"{name}: nonnegative finite number required")
    return value


def fields(value, required, optional=()):
    if (not isinstance(value, dict) or not set(required) <= value.keys()
            or set(value) - set(required) - set(optional)):
        raise ValueError("Invalid object fields")
    return value


def label(value, name):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or any(ord(c) < 32 for c in value)):
        raise ValueError(f"{name}: short printable string required")
    return value


def digest(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("SHA-256 required")
    return value


def advise(request, snapshot, candidates, *, now=None):
    """Rank qualified proposals, retaining every rejection and unknown cost.

    Memory estimates are peak increments, including model loading. Latencies
    cover one exact workload and include startup according to warm state.
    No network, subprocess, model, file write, or selected-route execution.
    """
    now = time.time() if now is None else number(now, "now")
    fields(request, ("task", "workload_sha256"), ("objective", "max_latency_ms"))
    if request["task"] not in TASKS:
        raise ValueError("Unsupported task")
    workload = digest(request["workload_sha256"])
    objective = request.get("objective", "latency")
    if objective not in ("latency", "cloud_spend"):
        raise ValueError("Unsupported objective")
    budget = number(request.get("max_latency_ms"), "latency budget", optional=True)
    fields(snapshot, ("observed_at", "hardware_key", "ram_available_bytes",
                      "commit_available_bytes", "disk_free_bytes", "gpu_free_bytes", "heavy_busy"))
    observed = number(snapshot["observed_at"], "observed_at")
    hardware = digest(snapshot["hardware_key"])
    for key in ("ram_available_bytes", "commit_available_bytes", "disk_free_bytes"):
        number(snapshot[key], key, integer=True, optional=True)
    if (not isinstance(snapshot["gpu_free_bytes"], list)
            or len(snapshot["gpu_free_bytes"]) > 32):
        raise ValueError("Invalid GPU inventory")
    for value in snapshot["gpu_free_bytes"]:
        number(value, "GPU free bytes", integer=True)
    if snapshot["heavy_busy"] is not None and type(snapshot["heavy_busy"]) is not bool:
        raise ValueError("Invalid heavy-operation state")
    if not isinstance(candidates, list) or len(candidates) > 32:
        raise ValueError("At most 32 candidates required")
    qualified, rejected, ids = [], [], set()
    for candidate in candidates:
        fields(candidate, ("id", "task", "device", "availability", "warm", "heavy",
                           "ram_bytes", "commit_bytes", "disk_bytes", "vram_bytes", "measurement"))
        route_id = label(candidate["id"], "route id")
        if route_id in ids:
            raise ValueError("Duplicate route id")
        ids.add(route_id)
        if candidate["device"] not in DEVICES or candidate["task"] not in TASKS:
            raise ValueError("Invalid route class")
        if candidate["availability"] not in ("ready", "unavailable", "unknown"):
            raise ValueError("Invalid availability")
        if type(candidate["warm"]) is not bool or type(candidate["heavy"]) is not bool:
            raise ValueError("Boolean warm and heavy required")
        for key in ("ram_bytes", "commit_bytes", "disk_bytes", "vram_bytes"):
            number(candidate[key], key, integer=True)
        reasons = []
        if candidate["task"] != request["task"]:
            reasons.append("task_mismatch")
        if candidate["availability"] != "ready":
            reasons.append("availability_" + candidate["availability"])
        local = candidate["device"] != "cloud"
        if local:
            if not 0 <= now - observed <= 60:
                reasons.append("resources_stale_or_future")
            for key, requirement, reserve in (
                ("ram_available_bytes", "ram_bytes", 5 * GIB),
                ("commit_available_bytes", "commit_bytes", 6 * GIB),
                ("disk_free_bytes", "disk_bytes", 15 * GIB),
            ):
                available = snapshot[key]
                if available is None:
                    reasons.append(key + "_unknown")
                elif candidate[requirement] + reserve > available:
                    reasons.append(key + "_insufficient")
            if candidate["device"] == "gpu":
                # One workload must fit one GPU. Never add unrelated VRAM pools.
                if not snapshot["gpu_free_bytes"]:
                    reasons.append("gpu_capacity_unknown")
                elif candidate["vram_bytes"] > max(snapshot["gpu_free_bytes"]):
                    reasons.append("single_gpu_vram_insufficient")
            if candidate["device"] == "npu":
                reasons.append("npu_capacity_not_observed")
            if candidate["heavy"] and snapshot["heavy_busy"] is not False:
                reasons.append("heavy_operation_busy_or_unknown")
        evidence = candidate["measurement"]
        total_ms = spend = None
        if evidence is None:
            reasons.append("measurement_missing")
        else:
            fields(evidence, ("workload_sha256", "hardware_key", "recorded_at", "samples",
                              "passed", "verifier_revision", "p50_ms", "p95_ms",
                              "cold_start_ms", "warm_start_ms", "cloud_cost_usd"))
            digest(evidence["workload_sha256"])
            digest(evidence["hardware_key"])
            label(evidence["verifier_revision"], "verifier revision")
            for key in ("samples", "passed"):
                number(evidence[key], key, integer=True)
            if evidence["passed"] > evidence["samples"]:
                raise ValueError("Passed count exceeds sample count")
            for key in ("p50_ms", "p95_ms", "cold_start_ms", "warm_start_ms"):
                number(evidence[key], key)
            if evidence["p95_ms"] < evidence["p50_ms"]:
                raise ValueError("p95 must not be below p50")
            number(evidence["recorded_at"], "measurement date")
            spend = number(evidence["cloud_cost_usd"], "cloud spend", optional=True)
            if evidence["workload_sha256"] != workload:
                reasons.append("workload_evidence_mismatch")
            if local and evidence["hardware_key"] != hardware:
                reasons.append("hardware_evidence_mismatch")
            if not 0 <= now - evidence["recorded_at"] <= 86400:
                reasons.append("measurement_stale_or_future")
            if evidence["samples"] < 3 or evidence["passed"] != evidence["samples"]:
                reasons.append("quality_gate_not_passed")
            start = "warm_start_ms" if candidate["warm"] else "cold_start_ms"
            total_ms = evidence["p95_ms"] + evidence[start]
            if not math.isfinite(total_ms):
                raise ValueError("Completion time overflow")
            if budget is not None and total_ms > budget:
                reasons.append("latency_budget_exceeded")
            if objective == "cloud_spend" and spend is None:
                reasons.append("cloud_spend_unknown")
        if reasons:
            rejected.append({"id": route_id, "reasons": reasons})
        else:
            qualified.append({"id": route_id, "device": candidate["device"],
                              "estimated_completion_p95_ms": total_ms,
                              "reported_cloud_cost_usd": spend})
    qualified.sort(key=lambda row: (
        (row["estimated_completion_p95_ms"] if objective == "latency"
         else row["reported_cloud_cost_usd"]), row["estimated_completion_p95_ms"], row["id"]))
    return {"schema": "parcimonia.local-compute/v1", "status": "proposed" if qualified else "abstain",
            "selected": qualified[0]["id"] if qualified else None, "qualified": qualified,
            "rejected": rejected, "objective": objective, "auto_act_allowed": False,
            "evidence_trust": "host_reported_not_independently_attested",
            "electricity_cost": None, "end_to_end_speedup": None}
