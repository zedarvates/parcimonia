"""Pure review of a host-owned memory reservation snapshot.

This adapts the HostMemoryGuard snapshot in Botte Secrete PR #166. It does not
import that backend, read its journal, acquire/release a reservation or execute
work. External anchors belong to the caller; hashes establish consistency, not
authenticity. Task/consumer/host bindings are not native provider observations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import re
import time

from .decision_json import canonical_json
from .execution_profiles import digest
from .local_compute import DEVICES, TASKS, fields, number


MAX_BYTES = 1024 ** 2
_PREFLIGHT_FIELDS = (
    "schema", "task_id", "task_revision", "route_id", "host_id", "hardware_key",
    "reviewed_at", "context_sha256", "runtime_requirements", "profile_assessment",
    "observation_review", "compute_advice", "compute_request_sha256",
    "supplied_policy_sha256", "snapshot_sha256", "candidate_sha256",
    "resource_declarations", "status", "reasons", "auto_act_allowed",
    "reservation_performed", "execution_performed", "evidence_trust",
    "reservation_exclusivity", "measured_savings", "preflight_sha256",
)
_CANDIDATE_FIELDS = (
    "id", "task", "device", "availability", "warm", "heavy", "ram_bytes",
    "commit_bytes", "disk_bytes", "vram_bytes", "measurement",
)
_EXPECTATION_FIELDS = (
    "schema", "preflight_sha256", "preflight_reviewed_at", "task_id", "task_revision",
    "route_id", "host_id", "hardware_key", "context_sha256", "candidate_sha256",
    "compute_request_sha256", "consumer_id", "provider_id", "provider_revision",
    "scope_id", "reservation_key", "requested_bytes", "ram_bytes", "commit_bytes",
    "budget_method", "max_age_seconds", "binding_provenance", "expectation_sha256",
)
_METRICS = (
    "total_bytes", "available_bytes", "commit_available_bytes", "reserved_bytes",
    "reservation_count", "system_reserve_bytes", "measured_at_utc", "source",
)


def _identity(value, name, maximum=128):
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or not value.isprintable() or value != value.strip()):
        raise ValueError(f"{name}: bounded printable identity required")


def _hash(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError("lowercase SHA-256 required")


def _bounded(value):
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise ValueError("host memory review input is nested too deeply")
        if isinstance(item, (dict, list, tuple)):
            if len(item) > 256:
                raise ValueError("at most 256 collection entries required")
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth + 1) for child in children)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            number(item, "input number")
    try:
        size = len(canonical_json(value).encode("utf-8"))
    except (TypeError, UnicodeError):
        raise ValueError("host memory review input must be JSON") from None
    if size > MAX_BYTES:
        raise ValueError("host memory review input exceeds 1 MiB")


def _anchor(record, key, expected):
    _hash(expected)
    _hash(record[key])
    unsigned = {name: value for name, value in record.items() if name != key}
    actual = digest(unsigned)
    if record[key] != actual or actual != expected:
        raise ValueError("external anchor mismatch")


def _integer(value, name, minimum=0):
    number(value, name, integer=True)
    if value < minimum:
        raise ValueError(f"{name}: minimum not satisfied")


def build_host_memory_expectation(preflight, candidate, compute_request, *,
                                  expected_preflight_sha256, consumer_id,
                                  provider_id, provider_revision, scope_id,
                                  reservation_key, max_age_seconds=2):
    """Bind a private native reservation key to a caller-held preflight anchor.

    The memory budget is explicitly max(RAM increment, commit increment), which
    conservatively reserves that one full budget against both native headrooms.
    The native provider does not observe consumer, task, host, TTL or fencing.
    An external hash is not authentication or an authorization to start work.
    """
    _bounded({"preflight": preflight, "candidate": candidate,
              "compute_request": compute_request})
    fields(preflight, _PREFLIGHT_FIELDS)
    if preflight["schema"] != "parcimonia.runtime-preflight/v1":
        raise ValueError("unsupported preflight schema")
    _anchor(preflight, "preflight_sha256", expected_preflight_sha256)
    if (preflight["status"] != "eligible_for_host_reservation"
            or preflight["reasons"] != []
            or any(preflight[name] is not False for name in (
                "auto_act_allowed", "reservation_performed", "execution_performed"))):
        raise ValueError("preflight is not a non-executing eligible proposal")
    for name in ("task_id", "task_revision", "route_id", "host_id"):
        _identity(preflight[name], name)
    for name in ("hardware_key", "context_sha256", "candidate_sha256",
                 "compute_request_sha256", "supplied_policy_sha256", "snapshot_sha256"):
        _hash(preflight[name])
    number(preflight["reviewed_at"], "preflight reviewed time")
    fields(candidate, _CANDIDATE_FIELDS)
    _identity(candidate["id"], "candidate id")
    if (candidate["task"] not in TASKS or candidate["device"] not in DEVICES
            or candidate["device"] not in ("cpu", "gpu")
            or candidate["availability"] != "ready"
            or type(candidate["warm"]) is not bool or type(candidate["heavy"]) is not bool):
        raise ValueError("invalid local candidate")
    for name in ("ram_bytes", "commit_bytes", "disk_bytes", "vram_bytes"):
        _integer(candidate[name], name)
    fields(compute_request, ("task", "workload_sha256"), ("objective", "max_latency_ms"))
    _hash(compute_request["workload_sha256"])
    if compute_request.get("objective", "latency") not in ("latency", "cloud_spend"):
        raise ValueError("unsupported compute objective")
    number(compute_request.get("max_latency_ms"), "latency budget", optional=True)
    if (compute_request["task"] != candidate["task"]
            or candidate["id"] != preflight["route_id"]
            or digest(candidate) != preflight["candidate_sha256"]
            or digest(compute_request) != preflight["compute_request_sha256"]):
        raise ValueError("candidate or compute request differs from preflight")
    compute = preflight["compute_advice"]
    health = preflight["observation_review"]
    profiles = preflight["profile_assessment"]
    runtime = preflight["runtime_requirements"]
    fields(runtime, ("context_sha256", "context", "requirements", "profile_refs"))
    context = runtime["context"]
    if (not isinstance(context, dict) or runtime["context_sha256"] != preflight["context_sha256"]
            or digest(context) != preflight["context_sha256"]
            or any(context.get(name) != preflight[name] for name in (
                "task_id", "task_revision", "route_id", "host_id", "hardware_key"))):
        raise ValueError("preflight runtime context contradicts identity binding")
    if (not isinstance(compute, dict) or compute.get("schema") != "parcimonia.local-compute/v1"
            or compute.get("status") != "proposed"
            or compute.get("selected") != candidate["id"]
            or compute.get("auto_act_allowed") is not False
            or not isinstance(health, dict) or health.get("schema") != "parcimonia.observation-review/v1"
            or health.get("status") != "ready"
            or health.get("auto_act_allowed") is not False
            or health.get("task_id") != preflight["task_id"]
            or health.get("task_revision") != preflight["task_revision"]
            or not isinstance(profiles, dict) or profiles.get("schema_version") != 1
            or type(profiles.get("schema_version")) is not int
            or profiles.get("kind") != "profiled-route-filter"
            or profiles.get("auto_act_allowed") is not False
            or not isinstance(profiles.get("assessment"), dict)
            or profiles["assessment"].get("auto_act_allowed") is not False
            or not isinstance(profiles.get("eligible_routes"), list)
            or preflight["route_id"] not in profiles.get("eligible_routes", [])):
        raise ValueError("preflight diagnostics contradict eligibility")
    for value, name in ((consumer_id, "consumer"), (provider_id, "provider"),
                        (provider_revision, "provider revision"), (scope_id, "scope")):
        _identity(value, name)
    _identity(reservation_key, "reservation key", 4096)
    number(max_age_seconds, "maximum observation age")
    budget = max(candidate["ram_bytes"], candidate["commit_bytes"])
    _integer(budget, "requested memory budget", 1)
    result = {
        "schema": "parcimonia.host-memory-expectation/v1",
        "preflight_sha256": expected_preflight_sha256,
        "preflight_reviewed_at": preflight["reviewed_at"],
        **{key: preflight[key] for key in (
            "task_id", "task_revision", "route_id", "host_id", "hardware_key",
            "context_sha256", "candidate_sha256", "compute_request_sha256")},
        "consumer_id": consumer_id, "provider_id": provider_id,
        "provider_revision": provider_revision, "scope_id": scope_id,
        "reservation_key": reservation_key, "requested_bytes": budget,
        "ram_bytes": candidate["ram_bytes"], "commit_bytes": candidate["commit_bytes"],
        "budget_method": "max_ram_commit", "max_age_seconds": max_age_seconds,
        "binding_provenance": "host_binding_not_provider_observed",
    }
    result["expectation_sha256"] = digest(result)
    _bounded(result)
    return result


def _expectation(value, anchor):
    _bounded(value)
    fields(value, _EXPECTATION_FIELDS)
    if value["schema"] != "parcimonia.host-memory-expectation/v1":
        raise ValueError("unsupported expectation schema")
    _anchor(value, "expectation_sha256", anchor)
    for name in ("task_id", "task_revision", "route_id", "host_id", "consumer_id",
                 "provider_id", "provider_revision", "scope_id"):
        _identity(value[name], name)
    _identity(value["reservation_key"], "reservation key", 4096)
    for name in ("preflight_sha256", "hardware_key", "context_sha256",
                 "candidate_sha256", "compute_request_sha256"):
        _hash(value[name])
    for name in ("max_age_seconds", "preflight_reviewed_at"):
        number(value[name], name)
    for name in ("requested_bytes", "ram_bytes", "commit_bytes"):
        _integer(value[name], name)
    if (value["budget_method"] != "max_ram_commit" or value["requested_bytes"] <= 0
            or value["requested_bytes"] != max(value["ram_bytes"], value["commit_bytes"])
            or value["binding_provenance"] != "host_binding_not_provider_observed"):
        raise ValueError("invalid expectation memory binding")


def _reservations(value):
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("at most 256 native reservations required")
    budgets = {}
    for row in value:
        fields(row, ("key", "requested_bytes"))
        _identity(row["key"], "native reservation key", 4096)
        _integer(row["requested_bytes"], "native requested memory", 1)
        if row["key"] in budgets:
            raise ValueError("duplicate native reservation key")
        budgets[row["key"]] = row["requested_bytes"]
    return budgets


def _utc_seconds(stamp):
    _identity(stamp, "native UTC timestamp")
    # datetime silently truncates longer fractional seconds. Refuse unsupported
    # precision rather than turning a future/stale instant into a current one.
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                    r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)", stamp) is None:
        raise ValueError("native UTC timestamp requires seconds with at most six decimal places")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid native UTC timestamp") from None
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("native memory timestamp must be UTC")
    delta = parsed - datetime(1970, 1, 1, tzinfo=timezone.utc)
    seconds = Fraction((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds, 1000000)
    if seconds < 0:
        raise ValueError("negative native UTC timestamp")
    return seconds


def review_host_memory_snapshot(expectation, snapshot, *,
                                expected_expectation_sha256, observed_at, now=None):
    """Review an atomic snapshot supplied by the host, never acquire its budget.

    A matching row binds only a native key and byte budget. Task, consumer,
    provider revision and host identity remain outside provider observations.
    Native TTL, fencing and continuing exclusivity cannot be established here.
    An unavailable registry remains unknown; nothing is released or retried.
    """
    _bounded({"expectation": expectation, "snapshot": snapshot})
    _expectation(expectation, expected_expectation_sha256)
    number(observed_at, "snapshot observation time")
    now = number(time.time() if now is None else now, "now")
    window = Fraction(expectation["max_age_seconds"])
    preflight_time = Fraction(expectation["preflight_reviewed_at"])
    reasons = []
    for instant, label in ((observed_at, "snapshot_observation"),
                           (expectation["preflight_reviewed_at"], "preflight")):
        age = Fraction(now) - Fraction(instant)
        if age < 0:
            reasons.append(label + "_future")
        elif age > window:
            reasons.append(label + "_stale")
    if Fraction(observed_at) < preflight_time:
        reasons.append("snapshot_observation_before_preflight")
    fields(snapshot, ("allowed", "reason"), (*_METRICS, "reservations"))
    if type(snapshot["allowed"]) is not bool:
        raise ValueError("native allowed must be a boolean")
    unavailable = snapshot["reason"] == "resource_state_unavailable"
    metrics = None
    if unavailable:
        fields(snapshot, ("allowed", "reason"), ("reservations",))
        if snapshot["allowed"] is not False:
            raise ValueError("unavailable snapshot cannot be allowed")
        if "reservations" in snapshot:
            _reservations(snapshot["reservations"])
        status = "unknown"
        reasons.append("resource_state_unavailable")
    else:
        fields(snapshot, ("allowed", "reason", *_METRICS, "reservations"))
        budgets = _reservations(snapshot["reservations"])
        for name in ("total_bytes", "available_bytes", "reserved_bytes",
                     "reservation_count", "system_reserve_bytes"):
            _integer(snapshot[name], name, 1 if name in ("total_bytes", "system_reserve_bytes") else 0)
        if (snapshot["available_bytes"] > snapshot["total_bytes"]
                or snapshot["reservation_count"] != len(budgets)
                or snapshot["reserved_bytes"] != sum(budgets.values())
                or snapshot["system_reserve_bytes"] < (snapshot["total_bytes"] + 9) // 10):
            raise ValueError("native memory metrics contradict reservation snapshot")
        if snapshot["source"] not in ("windows", "linux"):
            raise ValueError("unsupported native memory source")
        commit = snapshot["commit_available_bytes"]
        if commit is not None:
            _integer(commit, "commit available bytes")
        elif snapshot["source"] == "windows":
            raise ValueError("Windows commit headroom is required")
        measured = _utc_seconds(snapshot["measured_at_utc"])
        age = Fraction(now) - measured
        if age < 0:
            reasons.append("memory_measurement_future")
        elif age > window:
            reasons.append("memory_measurement_stale")
        if measured > Fraction(observed_at):
            reasons.append("memory_measurement_after_observation")
        if measured < preflight_time:
            reasons.append("memory_measurement_before_preflight")
        required = snapshot["reserved_bytes"] + snapshot["system_reserve_bytes"]
        native_reason = ("insufficient_ram" if required > snapshot["available_bytes"] else
                         "insufficient_commit" if commit is not None and required > commit else "admitted")
        if (snapshot["reason"] != native_reason
                or snapshot["allowed"] is not (native_reason == "admitted")):
            raise ValueError("native memory decision contradicts reported headroom")
        if native_reason != "admitted":
            reasons.append(native_reason)
        key = expectation["reservation_key"]
        if key not in budgets:
            reasons.append("reservation_missing")
        elif budgets[key] != expectation["requested_bytes"]:
            reasons.append("reservation_budget_mismatch")
        metrics = {name: snapshot[name] for name in _METRICS}
        status = "blocked" if reasons else "consistent_host_memory_snapshot"
    return {
        "schema": "parcimonia.host-memory-snapshot-review/v1", "status": status,
        "reasons": sorted(set(reasons)), "reviewed_at": now, "observed_at": observed_at,
        "expectation_sha256": expected_expectation_sha256,
        "preflight_sha256": expectation["preflight_sha256"],
        "snapshot_sha256": digest(snapshot), "memory_budget_bytes": expectation["requested_bytes"],
        "metrics": metrics, "binding_provenance": "host_binding_not_provider_observed",
        "native_task_consumer_host_identity": "not_observed",
        "reservation_expiry": "not_provided_by_provider",
        "fencing": "not_provided_by_provider", "reservation_exclusivity": "not_established",
        "auto_act_allowed": False, "reservation_performed": False, "execution_performed": False,
        "next_step": "host_revalidation_required" if status == "consistent_host_memory_snapshot" else "reconcile",
    }
