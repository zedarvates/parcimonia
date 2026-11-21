"""A pinned-route preflight is data review, not a host resource reservation."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from tiberium_ai.contracts import Task
from tiberium_ai.execution_profiles import ExecutionCatalog, digest
from tiberium_ai.local_compute import advise
from tiberium_ai.registry import RouteRegistry
from tiberium_ai.runtime_preflight import build_runtime_requirements, review_runtime_preflight

from test_execution_profiles import claim, host, policy, profile
from test_local_compute import inputs


NOW = 1000


def fixtures():
    compute_request, snapshot, candidate = inputs()
    task = Task("task-1", compute_request["task"], {"authored_input": "same workload"}, locality="local")
    root = profile("tool:compute")
    dependency = profile("tool:helper")
    root["dependencies"] = [{"id": dependency["id"], "revision": dependency["revision"],
                              "profile_sha256": digest(dependency)}]
    catalog = ExecutionCatalog("fixture/1", [root, dependency])
    registry = RouteRegistry.from_manifest({"schema_version": 1, "registry_version": "fixture/1",
        "routes": [{"route_id": candidate["id"], "capability_ids": ["compute@1"],
                    "estimated_cost": None, "estimated_latency_ms": None, "confidence": None,
                    "constraints": {"risk_classes": ["low"], "evidence_levels": ["normal"],
                                    "localities": ["local"]},
                    "verifier": {"verifier_id": "fixture/read", "verifier_version": "1"}}]})
    arguments = {"task_revision": "attempt-1", "host_id": "fixture-host",
                 "registry": registry, "catalog": catalog,
                 "bindings": {candidate["id"]: root["id"]}, "policy": policy(),
                 **host([root, dependency]), "compute_request": compute_request,
                 "snapshot": snapshot, "candidate": candidate, "now": NOW}
    arguments["observations"] = observations_for(task, candidate["id"], arguments)
    return task, candidate["id"], arguments


def observations_for(task, route_id, arguments):
    requirements = build_runtime_requirements(
        task, route_id, task_revision=arguments["task_revision"], host_id=arguments["host_id"],
        hardware_key=arguments["snapshot"]["hardware_key"], registry=arguments["registry"],
        catalog=arguments["catalog"], bindings=arguments["bindings"],
        required_capabilities=arguments.get("required_capabilities", ()),
        max_age_seconds=arguments.get("max_age_seconds", 60))
    observations = []
    for index, requirement in enumerate(requirements["requirements"]):
        observations.append({key: value for key, value in requirement.items()
                             if key not in ("id", "max_age_seconds")})
        observations[-1].update(id=f"health-{index}", requirement_id=requirement["id"],
                                task_id=task.task_id, task_revision=arguments["task_revision"],
                                observed_at=NOW - 1, outcome="pass")
    return observations


def test_exact_current_reports_prepare_host_reservation_without_authority_or_mutation():
    task, route_id, arguments = fixtures()
    original = deepcopy({key: value for key, value in arguments.items()
                         if key not in ("registry", "catalog")})
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "eligible_for_host_reservation"
    assert report["observation_review"]["status"] == "ready"
    assert len(report["runtime_requirements"]["profile_refs"]) == 2
    assert report["compute_advice"] == advise(arguments["compute_request"], arguments["snapshot"],
                                               [arguments["candidate"]], now=NOW)
    assert report["auto_act_allowed"] is False
    assert report["reservation_performed"] is False
    assert report["execution_performed"] is False
    assert report["reservation_exclusivity"] == "not_established"
    assert report["evidence_trust"] == "host_reported_not_independently_attested"
    assert original == {key: value for key, value in arguments.items()
                        if key not in ("registry", "catalog")}
    assert report["resource_declarations"]["unknown_profile_ids"] == ["tool:compute", "tool:helper"]
    assert report["resource_declarations"]["capacity_measured"] is False


@pytest.mark.parametrize("profile_index", [0, 1])
@pytest.mark.parametrize("tag,reason", [
    ("gpu", "profile_gpu_requirement_mismatch"),
    ("ram-heavy", "profile_heavy_requirement_mismatch"),
    ("vram-heavy", "profile_heavy_requirement_mismatch"),
])
def test_explicit_profile_resource_requirements_cannot_hide_behind_cpu_or_light_candidate(profile_index, tag, reason):
    task, route_id, arguments = fixtures()
    profiles = arguments["catalog"].to_record()["profiles"]
    profiles[profile_index]["facets"]["resources"] = claim([tag])
    profiles[0]["dependencies"][0]["profile_sha256"] = digest(profiles[1])
    arguments["catalog"] = ExecutionCatalog("fixture/2", profiles)
    arguments.update(host(profiles))
    arguments["snapshot"]["gpu_free_bytes"] = []
    arguments["snapshot"]["heavy_busy"] = True
    arguments["observations"] = observations_for(task, route_id, arguments)
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["compute_advice"]["selected"] == route_id
    assert report["status"] == "blocked"
    assert reason in report["reasons"]


def test_positive_vram_estimate_requires_gpu_candidate():
    task, route_id, arguments = fixtures()
    arguments["candidate"]["vram_bytes"] = 1
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "blocked"
    assert "candidate_device_vram_mismatch" in report["reasons"]


def test_large_mixed_measurement_date_cannot_round_expired_measurement_to_current():
    task, route_id, arguments = fixtures()
    arguments["now"] = float(10 ** 18)
    arguments["snapshot"]["observed_at"] = 10 ** 18
    arguments["candidate"]["measurement"]["recorded_at"] = 10 ** 18 - 86401
    for item in arguments["observations"]:
        item["observed_at"] = 10 ** 18
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["compute_advice"]["selected"] == route_id
    assert report["status"] == "blocked"
    assert "compute_measurement_stale_or_future" in report["reasons"]


def test_availability_is_required_even_when_original_policy_omits_it():
    task, route_id, arguments = fixtures()
    del arguments["policy"]["required"]["availability"]
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "eligible_for_host_reservation"
    effective = report["profile_assessment"]["assessment"]["policy"]
    assert effective["required"]["availability"] == ["available"]
    assert effective["allowed"]["availability"] == ["available"]
    assert "availability" not in arguments["policy"]["required"]


def test_imposed_availability_does_not_relax_existing_or_invalid_policy():
    task, route_id, arguments = fixtures()
    arguments["policy"]["allowed"]["availability"] = ["unavailable"]
    assert review_runtime_preflight(task, route_id, **arguments)["status"] == "blocked"
    arguments["policy"]["allowed"]["availability"] = ["unsupported-tag"]
    with pytest.raises(ValueError, match="unknown tag"):
        review_runtime_preflight(task, route_id, **arguments)


def test_one_shot_host_attestations_are_snapshotted_before_reusing_profile_checks():
    task, route_id, arguments = fixtures()
    arguments["trusted_claims"] = iter(arguments["trusted_claims"])
    assert review_runtime_preflight(task, route_id, **arguments)["status"] == "eligible_for_host_reservation"


@pytest.mark.parametrize("change", ["unavailable", "both", "unknown", "missing_dependency", "source_changed"])
def test_profile_availability_dependencies_and_current_hashes_cannot_be_skipped(change):
    task, route_id, arguments = fixtures()
    profiles = arguments["catalog"].to_record()["profiles"]
    if change == "unavailable":
        profiles[1]["facets"]["availability"] = claim(["unavailable"])
    elif change == "both":
        profiles[1]["facets"]["availability"] = claim(["available", "unavailable"])
    elif change == "unknown":
        profiles[1]["facets"]["availability"] = claim(None, "unknown")
    elif change == "missing_dependency":
        profiles.pop()
    else:
        arguments["observed_content"][profiles[0]["id"]] = "c" * 64
    if change != "source_changed":
        arguments["catalog"] = ExecutionCatalog("fixture/2", profiles)
        arguments.update(host(profiles))
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "blocked"
    assert "chosen_route_profile_ineligible" in report["reasons"]


@pytest.mark.parametrize("change", ["task_revision", "host_id", "hardware", "task_inputs", "route_manifest"])
def test_health_reports_are_bound_to_complete_context_even_when_versions_are_reused(change):
    task, route_id, arguments = fixtures()
    if change == "task_revision":
        arguments["task_revision"] = "attempt-2"
    elif change == "host_id":
        arguments["host_id"] = "another-host"
    elif change == "hardware":
        arguments["snapshot"]["hardware_key"] = "c" * 64
        arguments["candidate"]["measurement"]["hardware_key"] = "c" * 64
    elif change == "task_inputs":
        task = Task(task.task_id, task.kind, {"authored_input": "changed"}, locality=task.locality)
    else:
        manifest = deepcopy(arguments["registry"].route(route_id))
        from dataclasses import replace
        arguments["registry"] = RouteRegistry(arguments["registry"].version,
                                               [replace(manifest, estimated_cost=1)])
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "blocked"
    assert "runtime_health_not_current_pass" in report["reasons"]


@pytest.mark.parametrize("outcome,expected", [("fail", "blocked"), ("unknown", "needs_observation")])
def test_latest_health_negative_supersedes_success(outcome, expected):
    task, route_id, arguments = fixtures()
    arguments["observations"].append({**arguments["observations"][0], "id": "later",
                                      "observed_at": NOW, "outcome": outcome})
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "blocked"
    assert report["observation_review"]["status"] == expected


@pytest.mark.parametrize("when,state", [(NOW - 61, "stale"), (NOW + 1, "missing")])
def test_stale_or_future_health_reports_never_prepare_reservation(when, state):
    task, route_id, arguments = fixtures()
    arguments["observations"][0]["observed_at"] = when
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "blocked"
    assert state in {row["state"] for row in report["observation_review"]["requirements"]}


def test_missing_health_for_transitive_dependency_blocks_and_reordering_changes_nothing():
    task, route_id, arguments = fixtures()
    first = review_runtime_preflight(task, route_id, **arguments)
    arguments["observations"].reverse()
    assert review_runtime_preflight(task, route_id, **arguments) == first
    arguments["observations"].pop()
    assert review_runtime_preflight(task, route_id, **arguments)["status"] == "blocked"


@pytest.mark.parametrize("change,reason", [
    ("candidate", "compute_candidate_route_mismatch"),
    ("kind", "compute_task_kind_mismatch"), ("cloud", "local_route_required"),
    ("missing_capability", "chosen_route_profile_ineligible"),
])
def test_pinned_route_kind_location_and_capability_are_not_reclassified(change, reason):
    task, route_id, arguments = fixtures()
    if change == "candidate":
        arguments["candidate"]["id"] = "another-route"
    elif change == "kind":
        task = Task(task.task_id, "vision", task.inputs, locality=task.locality)
    elif change == "cloud":
        arguments["candidate"]["device"] = "cloud"
    else:
        arguments["required_capabilities"] = ["absent@1"]
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "blocked"
    assert reason in report["reasons"]
    assert report["route_id"] == route_id


def test_snapshot_candidate_and_measurements_are_passed_unchanged_to_adviser():
    task, route_id, arguments = fixtures()
    arguments["candidate"]["heavy"] = True
    arguments["snapshot"]["heavy_busy"] = True
    with patch("tiberium_ai.runtime_preflight.advise", wraps=advise) as call:
        report = review_runtime_preflight(task, route_id, **arguments)
    passed = call.call_args.args
    assert passed[0] is arguments["compute_request"]
    assert passed[1] is arguments["snapshot"]
    assert passed[2][0] is arguments["candidate"]
    assert arguments["snapshot"]["heavy_busy"] is True
    assert report["status"] == "blocked"
    assert "heavy_operation_busy_or_unknown" in report["compute_advice"]["rejected"][0]["reasons"]


def test_old_large_resource_dates_cannot_round_to_fresh():
    task, route_id, arguments = fixtures()
    arguments["now"] = float(10 ** 18)
    arguments["snapshot"]["observed_at"] = 10 ** 18 - 61
    arguments["candidate"]["measurement"]["recorded_at"] = 10 ** 18
    for observation in arguments["observations"]:
        observation["observed_at"] = 10 ** 18
    report = review_runtime_preflight(task, route_id, **arguments)
    assert report["status"] == "blocked"
    assert "resource_snapshot_stale_or_future" in report["reasons"]


def test_requirement_helper_refuses_more_than_64_profiles_instead_of_truncating():
    task, route_id, arguments = fixtures()
    profiles = [profile(f"tool:{index}") for index in range(65)]
    for index in reversed(range(64)):
        profiles[index]["dependencies"] = [{"id": profiles[index + 1]["id"],
            "revision": profiles[index + 1]["revision"],
            "profile_sha256": digest(profiles[index + 1])}]
    # The helper follows explicit IDs; the normal profile filter separately
    # rejects such a deep dependency chain before a preflight could qualify.
    arguments["catalog"] = ExecutionCatalog("fixture/large", profiles)
    arguments["bindings"] = {route_id: profiles[0]["id"]}
    with pytest.raises(ValueError, match="64_requirements"):
        build_runtime_requirements(task, route_id, task_revision="1", host_id="host",
            hardware_key=arguments["snapshot"]["hardware_key"], registry=arguments["registry"],
            catalog=arguments["catalog"], bindings=arguments["bindings"])
