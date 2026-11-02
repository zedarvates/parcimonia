"""Opt-in interoperability with a pinned host backend and temporary state only.

Capacity and preflight inputs are authored fixtures. The supplied backend really
reads/writes its own temporary reservation state; no workload is launched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time
from types import ModuleType

from tiberium_ai.contracts import Task
from tiberium_ai.execution_profiles import ExecutionCatalog, claim_attestation
from tiberium_ai.host_memory_receipt import (
    build_host_memory_expectation, review_host_memory_snapshot,
)
from tiberium_ai.local_compute import GIB
from tiberium_ai.registry import RouteRegistry
from tiberium_ai.runtime_preflight import build_runtime_requirements, review_runtime_preflight


def authored_preflight():
    now = time.time()
    hardware = sha256(b"authored hardware identity").hexdigest()
    workload = sha256(b"{}").hexdigest()
    task = Task("fixture-memory-001", "json_minify", {"text": "{}"}, locality="local")

    def claim(tags):
        return {"status": "verified", "tags": tags, "source": "fixture",
                "observed_at": datetime.now(timezone.utc).isoformat(), "evidence": "fixture/1"}

    profile = {"schema_version": 1, "taxonomy_version": "execution-tags/1",
        "id": "tool:fixture", "kind": "mechanism", "revision": "1",
        "content_sha256": sha256(b"authored tool").hexdigest(), "dependencies": [],
        "facets": {"availability": claim(["available"]), "effects": claim(["read"]),
                   "resources": claim(["cpu"]), "locations": claim(["local"])}}
    catalog = ExecutionCatalog("fixture/1", [profile])
    registry = RouteRegistry.from_manifest({"schema_version": 1, "registry_version": "fixture/1",
        "routes": [{"route_id": "cpu", "capability_ids": ["json@1"],
            "estimated_cost": None, "estimated_latency_ms": None, "confidence": None,
            "constraints": {"risk_classes": ["low"], "evidence_levels": ["normal"],
                            "localities": ["local"]},
            "verifier": {"verifier_id": "fixture.json", "verifier_version": "1"}}]})
    compute = {"task": "json_minify", "workload_sha256": workload}
    snapshot = {"observed_at": now, "hardware_key": hardware,
        "ram_available_bytes": 32 * GIB, "commit_available_bytes": 40 * GIB,
        "disk_free_bytes": 100 * GIB, "gpu_free_bytes": [], "heavy_busy": False}
    candidate = {"id": "cpu", "task": "json_minify", "device": "cpu",
        "availability": "ready", "warm": True, "heavy": False,
        "ram_bytes": GIB // 2, "commit_bytes": GIB, "disk_bytes": 0, "vram_bytes": 0,
        "measurement": {"workload_sha256": workload, "hardware_key": hardware,
            "recorded_at": now, "samples": 3, "passed": 3, "verifier_revision": "fixture/1",
            "p50_ms": 1, "p95_ms": 2, "cold_start_ms": 0, "warm_start_ms": 0,
            "cloud_cost_usd": None}}
    common = {"task_revision": "fixture/1", "host_id": "fixture-host", "registry": registry,
              "catalog": catalog, "bindings": {"cpu": profile["id"]}}
    required = build_runtime_requirements(task, "cpu", hardware_key=hardware, **common)
    observations = []
    for index, requirement in enumerate(required["requirements"]):
        row = {key: value for key, value in requirement.items() if key not in ("id", "max_age_seconds")}
        row.update(id=f"fixture-health-{index}", requirement_id=requirement["id"],
                   task_id=task.task_id, task_revision="fixture/1", observed_at=now, outcome="pass")
        observations.append(row)
    report = review_runtime_preflight(task, "cpu", **common,
        policy={"version": "fixture/1", "required": {},
                "allowed": {"effects": ["read"], "locations": ["local"]}, "require_verified": True},
        observed_content={profile["id"]: profile["content_sha256"]},
        trusted_claims=[claim_attestation(profile, facet) for facet in profile["facets"]],
        observations=observations, compute_request=compute, snapshot=snapshot, candidate=candidate, now=now)
    if report["status"] != "eligible_for_host_reservation":
        raise RuntimeError("Authored preflight was not eligible")
    return report, candidate, compute


def authored_capacity():
    return {"total_bytes": 32 * GIB, "available_bytes": 16 * GIB,
            "commit_available_bytes": None, "commit_required": False, "source": "linux",
            "measured_monotonic": time.monotonic(),
            "measured_at_utc": datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-memory-source", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    args = parser.parse_args()
    data = args.host_memory_source.read_bytes()
    actual = sha256(data).hexdigest()
    if actual != args.expected_source_sha256:
        parser.error("Backend source hash mismatch; no backend imported")
    # Execute precisely the bytes checked above, without reopening a mutable
    # path between identity checking and loading the explicitly selected code.
    backend = ModuleType("pinned_host_memory_demo")
    exec(compile(data, "<pinned_host_memory_demo>", "exec"), backend.__dict__)
    preflight, candidate, compute = authored_preflight()
    expectation = build_host_memory_expectation(preflight, candidate, compute,
        expected_preflight_sha256=preflight["preflight_sha256"], consumer_id="fixture-job",
        provider_id="botte.host-memory", provider_revision=actual, scope_id="temporary-fixture",
        reservation_key="fixture:job")
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="parcimonia-memory-fixture-") as temporary:
        guard = backend.HostMemoryGuard(Path(temporary) / "state.json", probe=authored_capacity)

        def inspect(label):
            snapshot = guard.snapshot(include_reservations=True)
            result = review_host_memory_snapshot(expectation, snapshot,
                expected_expectation_sha256=expectation["expectation_sha256"], observed_at=time.time())
            outcomes.append({"phase": label, "status": result["status"], "reasons": result["reasons"]})
            return result

        if inspect("before")["reasons"] != ["reservation_missing"]:
            raise RuntimeError("Expected the temporary reservation to be absent")
        acquisition = guard.reserve(expectation["reservation_key"], expectation["requested_bytes"])
        if acquisition["allowed"] is not True:
            raise RuntimeError("Temporary native acquisition was refused")
        if inspect("reserved")["status"] != "consistent_host_memory_snapshot":
            raise RuntimeError("Temporary native snapshot did not match the expectation")
        guard.release(expectation["reservation_key"])
        if inspect("released")["reasons"] != ["reservation_missing"]:
            raise RuntimeError("Expected the temporary reservation to have been released")
    print(json.dumps({"backend_source_sha256": actual, "data_origin": "authored_capacity",
        "backend_state": "real_temporary_files", "outcomes": outcomes,
        "workload_executed": False, "target_host_qualified": False,
        "local_concurrency_test": "not_performed_by_this_example"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
