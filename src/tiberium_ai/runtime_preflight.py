"""Pure preflight of a pinned local route before host-owned reservation.

The existing registry/profile filter, observation review and compute adviser
remain the owners of their checks. This adapter neither chooses another route,
collects observations, reserves a slot nor authorizes an action. Reports and
host labels remain supplied data, not independently attested facts.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
import time

from .contracts import Task
from .execution_profiles import ExecutionCatalog, digest
from .local_compute import advise, digest as validate_digest, number
from .observation_review import review_observations
from .profiled_selection import filter_profiled_routes
from .registry import RouteRegistry


HEALTH_VERIFIER_ID = "parcimonia.runtime-health"
HEALTH_VERIFIER_VERSION = "1"


class _RuntimeRequirementsUnavailable(ValueError):
    """A bounded, exact health requirement set cannot be constructed."""


def _identity(value, name):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or not value.isprintable() or value != value.strip()):
        raise ValueError(f"{name}: a short nonempty printable identity is required")
    return value


def _inputs(task, route_id, task_revision, host_id, registry, catalog, bindings,
            max_age_seconds, required_capabilities):
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    _identity(task.task_id, "task id")
    _identity(route_id, "route id")
    _identity(task_revision, "task revision")
    _identity(host_id, "host id")
    if not isinstance(registry, RouteRegistry) or not isinstance(catalog, ExecutionCatalog):
        raise TypeError("a route registry and execution catalog are required")
    if not isinstance(bindings, dict):
        raise ValueError("bindings must be an object")
    number(max_age_seconds, "maximum observation age")
    if not isinstance(required_capabilities, (list, tuple)):
        raise ValueError("required_capabilities must be a list or tuple")
    if len(required_capabilities) > 64:
        raise ValueError("at most 64 unique required capabilities are allowed")
    for capability in required_capabilities:
        _identity(capability, "required capability")
    if len(set(required_capabilities)) != len(required_capabilities):
        raise ValueError("required capabilities must be unique")


def build_runtime_requirements(task, route_id, *, task_revision, host_id,
                               hardware_key, registry, catalog, bindings,
                               max_age_seconds=60, required_capabilities=()):
    """Build exact health requirements for the chosen profile and its closure.

    The host supplies one health observation for each returned requirement.
    A pass means that its named health verifier reports that this exact profile
    is currently available on this host; it does not prove inference quality.
    Requirements bind the complete task, route manifest (not just its version),
    catalog/profile references, host and hardware identity. A changed context
    needs new matching reports. Missing bindings/profiles or more than 64
    profiles refuse construction rather than returning a partial closure.
    """
    _inputs(task, route_id, task_revision, host_id, registry, catalog, bindings,
            max_age_seconds, required_capabilities)
    validate_digest(hardware_key)
    manifest = registry.route(route_id)
    if route_id not in bindings:
        raise _RuntimeRequirementsUnavailable("chosen_route_binding_missing")
    pending = [bindings[route_id]]
    profiles = {}
    while pending:
        identifier = pending.pop()
        if identifier in profiles:
            continue
        try:
            profile = catalog.profile(identifier)
        except ValueError:
            raise _RuntimeRequirementsUnavailable("runtime_profile_missing") from None
        profiles[identifier] = profile
        if len(profiles) > 64:
            raise _RuntimeRequirementsUnavailable("runtime_profile_closure_exceeds_64_requirements")
        for dependency in profile["dependencies"]:
            try:
                child = catalog.profile(dependency["id"])
            except ValueError:
                raise _RuntimeRequirementsUnavailable("runtime_profile_missing") from None
            if child["revision"] != dependency["revision"] or digest(child) != dependency["profile_sha256"]:
                raise _RuntimeRequirementsUnavailable("runtime_dependency_reference_mismatch")
            pending.append(dependency["id"])
    references = [catalog.reference(identifier) for identifier in sorted(profiles)]
    task_hash = digest(asdict(task))
    manifest_hash = digest(asdict(manifest))
    context = {"task_id": task.task_id, "task_revision": task_revision,
               "task_sha256": task_hash, "route_id": route_id,
               "route_manifest_sha256": manifest_hash,
               "registry_version": registry.version,
               "catalog_sha256": catalog.snapshot_hash,
               "host_id": host_id, "hardware_key": hardware_key,
               "required_capabilities": sorted(required_capabilities),
               "profile_refs": references}
    context_hash = digest(context)
    requirements = []
    for reference in references:
        profile_key = digest(reference["id"])
        requirements.append({
            "id": "availability:" + profile_key,
            "source_id": "profile:" + profile_key,
            "source_revision": reference["profile_sha256"],
            "input_sha256": digest({"context_sha256": context_hash,
                                    "profile_ref": reference}),
            "verifier_id": HEALTH_VERIFIER_ID,
            "verifier_version": HEALTH_VERIFIER_VERSION,
            "max_age_seconds": max_age_seconds,
        })
    return {"context_sha256": context_hash, "context": context,
            "requirements": sorted(requirements, key=lambda item: item["id"]),
            "profile_refs": references}


def _availability_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    effective = deepcopy(policy)
    for field in ("required", "allowed"):
        if not isinstance(effective.get(field), dict):
            raise ValueError("policy facets must be objects")
        values = effective[field].get("availability", [])
        if not isinstance(values, list):
            raise ValueError("availability policy must be a list")
    required = effective["required"].get("availability", [])
    effective["required"]["availability"] = list(dict.fromkeys([*required, "available"]))
    # Preserve existing restrictions rather than replacing an incompatible one.
    allowed = effective["allowed"].get("availability", ["available"])
    effective["allowed"]["availability"] = [value for value in allowed if value == "available"]
    return effective


def review_runtime_preflight(task, route_id, *, task_revision, host_id, registry,
                             catalog, bindings, policy, observed_content,
                             observations, compute_request, snapshot, candidate,
                             trusted_claims=(), max_age_seconds=60,
                             required_capabilities=(), now=None):
    """Review one chosen local route and retain all three diagnostic reports.

    ``task.kind`` must equal the compute task. The host retains its existing
    workload SHA-256 convention and is responsible for relating that workload
    to the task's inputs; this adapter never invents a replacement hash.
    ``snapshot``, ``candidate`` and its measurements pass unchanged to advise.
    Availability is mandatory even if omitted from the supplied profile policy.

    ``eligible_for_host_reservation`` is only consistency of supplied reports,
    not admission to execute. The host must acquire/revalidate its real slot
    atomically and recheck resources before starting. In particular a held
    heavy-operation slot is not rewritten into an idle snapshot.
    """
    _inputs(task, route_id, task_revision, host_id, registry, catalog, bindings,
            max_age_seconds, required_capabilities)
    now = number(time.time() if now is None else now, "now")
    trusted_claims = tuple(trusted_claims)
    # Validate the original policy before intersecting its availability facet;
    # an unknown tag must not be silently discarded into a valid restriction.
    catalog.assess((), policy, observed_content=observed_content, trusted_claims=trusted_claims)
    effective_policy = _availability_policy(policy)
    kept, profile_report = filter_profiled_routes(
        registry, task, catalog=catalog, bindings=bindings, policy=effective_policy,
        observed_content=observed_content, trusted_claims=trusted_claims,
        required_capabilities=required_capabilities)
    compute_report = advise(compute_request, snapshot, [candidate], now=now)
    reasons = []
    if route_id not in {route.route_id for route in kept}:
        reasons.append("chosen_route_profile_ineligible")
    if candidate["id"] != route_id:
        reasons.append("compute_candidate_route_mismatch")
    if compute_request["task"] != task.kind:
        reasons.append("compute_task_kind_mismatch")
    if candidate["device"] == "cloud":
        reasons.append("local_route_required")
    if compute_report["selected"] != route_id:
        reasons.append("chosen_route_compute_ineligible")
    # The adviser owns the fixed 60-second resource rule. Comparing its bound
    # exactly here also avoids float/int subtraction hiding stale large dates.
    age = Fraction(now) - Fraction(snapshot["observed_at"])
    if age < 0 or age > 60:
        reasons.append("resource_snapshot_stale_or_future")
    measurement = candidate["measurement"]
    if measurement is not None:
        measurement_age = Fraction(now) - Fraction(measurement["recorded_at"])
        if measurement_age < 0 or measurement_age > 86400:
            reasons.append("compute_measurement_stale_or_future")
    if candidate["vram_bytes"] > 0 and candidate["device"] != "gpu":
        reasons.append("candidate_device_vram_mismatch")
    requirements = None
    observation_report = None
    declared_resources = set()
    unknown_resource_profiles = []
    if route_id in {route.route_id for route in kept}:
        try:
            requirements = build_runtime_requirements(
                task, route_id, task_revision=task_revision, host_id=host_id,
                hardware_key=snapshot["hardware_key"], registry=registry, catalog=catalog,
                bindings=bindings, max_age_seconds=max_age_seconds,
                required_capabilities=required_capabilities)
        except _RuntimeRequirementsUnavailable as error:
            reasons.append(str(error))
    if requirements is not None:
        for reference in requirements["profile_refs"]:
            resource_claim = catalog.profile(reference["id"])["facets"].get("resources")
            if resource_claim is None or resource_claim["status"] == "unknown":
                unknown_resource_profiles.append(reference["id"])
            else:
                declared_resources.update(resource_claim["tags"])
        # Positive declarations are requirements, not measured capacity. Missing
        # tags do not establish absence of a resource requirement.
        if (declared_resources.intersection(("gpu", "vram-heavy"))
                and candidate["device"] != "gpu"):
            reasons.append("profile_gpu_requirement_mismatch")
        if declared_resources.intersection(("ram-heavy", "vram-heavy")) and not candidate["heavy"]:
            reasons.append("profile_heavy_requirement_mismatch")
        observation_report = review_observations({
            "task_id": task.task_id, "task_revision": task_revision,
            "requirements": requirements["requirements"],
            "observations": observations, "probes": []}, now=now)
        if observation_report["status"] != "ready":
            reasons.append("runtime_health_not_current_pass")
    report = {
        "schema": "parcimonia.runtime-preflight/v1", "task_id": task.task_id,
        "task_revision": task_revision, "route_id": route_id,
        "host_id": host_id, "hardware_key": snapshot["hardware_key"],
        "reviewed_at": now,
        "context_sha256": None if requirements is None else requirements["context_sha256"],
        "runtime_requirements": requirements,
        "profile_assessment": profile_report, "observation_review": observation_report,
        "compute_advice": compute_report, "compute_request_sha256": digest(compute_request),
        "supplied_policy_sha256": digest(policy),
        "snapshot_sha256": digest(snapshot), "candidate_sha256": digest(candidate),
        "resource_declarations": {"tags": sorted(declared_resources),
                                  "unknown_profile_ids": unknown_resource_profiles,
                                  "capacity_measured": False},
        "status": "blocked" if reasons else "eligible_for_host_reservation",
        "reasons": sorted(set(reasons)), "auto_act_allowed": False,
        "reservation_performed": False, "execution_performed": False,
        "evidence_trust": "host_reported_not_independently_attested",
        "reservation_exclusivity": "not_established", "measured_savings": None,
    }
    report["preflight_sha256"] = digest(report)
    return report
