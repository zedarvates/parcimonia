"""Review caller-reported observations before proposing another observation.

This module is self-contained for vendoring into the local plugin. It performs
no file, network, model or action calls. With an explicit ``now`` its result is
deterministic. Matching hashes, dates and verifier identities establish report
consistency, not the truth of a report or permission to act.
"""
from __future__ import annotations

import math
import time
from fractions import Fraction


MAX_NUMBER = 10 ** 18
REQUEST_FIELDS = ("task_id", "task_revision", "requirements", "observations", "probes")
REQUIREMENT_FIELDS = (
    "id", "source_id", "source_revision", "input_sha256", "verifier_id",
    "verifier_version", "max_age_seconds",
)
OBSERVATION_FIELDS = (
    "id", "requirement_id", "task_id", "task_revision", "source_id",
    "source_revision", "input_sha256", "verifier_id", "verifier_version",
    "observed_at", "outcome",
)
PROBE_FIELDS = ("id", "requirement_ids", "estimated_latency_ms")
NEEDS_OBSERVATION = frozenset(("missing", "stale", "unknown", "conflict"))


def _fields(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("Invalid object fields")


def _label(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or not value.isprintable() or not value.strip()):
        raise ValueError("A short nonempty printable label is required")
    return value


def _number(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= MAX_NUMBER or not math.isfinite(value)):
        raise ValueError("A bounded finite nonnegative number is required")
    return value


def _digest(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("A lowercase SHA-256 is required")


def _collection(value, maximum, *, nonempty=False):
    if (not isinstance(value, list) or len(value) > maximum
            or (nonempty and not value)):
        raise ValueError("Invalid collection size")


def _unique_id(item, seen):
    identifier = _label(item["id"])
    if identifier in seen:
        raise ValueError("Duplicate id")
    seen.add(identifier)


def _validate(request):
    _fields(request, REQUEST_FIELDS)
    for key in ("task_id", "task_revision"):
        _label(request[key])
    _collection(request["requirements"], 64, nonempty=True)
    _collection(request["observations"], 128)
    _collection(request["probes"], 32)
    requirements = {}
    for requirement in request["requirements"]:
        _fields(requirement, REQUIREMENT_FIELDS)
        _unique_id(requirement, set(requirements))
        for key in ("source_id", "source_revision", "verifier_id", "verifier_version"):
            _label(requirement[key])
        _digest(requirement["input_sha256"])
        _number(requirement["max_age_seconds"])
        requirements[requirement["id"]] = requirement
    observation_ids = set()
    for observation in request["observations"]:
        _fields(observation, OBSERVATION_FIELDS)
        _unique_id(observation, observation_ids)
        for key in ("requirement_id", "task_id", "task_revision", "source_id",
                    "source_revision", "verifier_id", "verifier_version"):
            _label(observation[key])
        _digest(observation["input_sha256"])
        _number(observation["observed_at"])
        if observation["outcome"] not in ("pass", "fail", "unknown"):
            raise ValueError("Invalid observation outcome")
    probe_ids = set()
    for probe in request["probes"]:
        _fields(probe, PROBE_FIELDS)
        _unique_id(probe, probe_ids)
        _collection(probe["requirement_ids"], 64, nonempty=True)
        references = [_label(value) for value in probe["requirement_ids"]]
        if len(set(references)) != len(references) or set(references) - set(requirements):
            raise ValueError("Probe requirement references must be unique and known")
        if probe["estimated_latency_ms"] is not None:
            _number(probe["estimated_latency_ms"])
    return requirements


def review_observations(request, *, now=None):
    """Return an advisory readiness report and one deterministic probe proposal.

    Every request field and nested field is required. There must be 1..64
    requirements, at most 128 observations and at most 32 probes. Unknown
    observation requirement IDs are retained as rejections; unknown probe IDs
    are invalid input. All labels have 1..128 printable characters and all
    numeric values are in [0, 10**18], excluding booleans and non-finite values.

    A usable observation must match the task and requirement's exact source,
    input hash and verifier identity, and have age in [0, max_age_seconds].
    The most recent usable observation wins, including fail or unknown after
    an earlier pass. Different outcomes tied at that timestamp are a conflict.
    With no usable observation, an otherwise matching old observation yields
    stale; incompatible or future observations never count as current evidence.

    ``ready`` means all current reports say pass; ``blocked`` means at least
    one current report says fail. All other cases need another observation.
    This is never independent verification or authorization. Probes are ranked
    by unresolved-requirement coverage, known then lower estimated latency,
    and stable ID. These are caller estimates and a coverage heuristic, not
    calibrated information gain or measured savings.
    """
    requirements = _validate(request)
    now = _number(time.time() if now is None else now)
    current = {identifier: [] for identifier in requirements}
    stale = {identifier: [] for identifier in requirements}
    rejected = []
    for observation in request["observations"]:
        requirement_id = observation["requirement_id"]
        requirement = requirements.get(requirement_id)
        reasons = []
        if requirement is None:
            reasons.append("requirement_unknown")
        else:
            for key in ("task_id", "task_revision"):
                if observation[key] != request[key]:
                    reasons.append(key + "_mismatch")
            for key in ("source_id", "source_revision", "input_sha256",
                        "verifier_id", "verifier_version"):
                if observation[key] != requirement[key]:
                    reasons.append(key + "_mismatch")
            if observation["observed_at"] > now:
                reasons.append("observation_future")
            elif (Fraction(now) - Fraction(observation["observed_at"])
                  > Fraction(requirement["max_age_seconds"])):
                # Only identity-compatible old reports establish a stale state.
                if not reasons:
                    stale[requirement_id].append(observation)
                reasons.append("observation_stale")
        if reasons:
            rejected.append({"id": observation["id"], "requirement_id": requirement_id,
                             "reasons": reasons})
        else:
            current[requirement_id].append(observation)

    rows = []
    for identifier in sorted(requirements):
        compatible = current[identifier]
        considered = sorted(observation["id"] for observation in compatible)
        latest_at = None
        selected = []
        reasons = []
        if compatible:
            latest_at = max(observation["observed_at"] for observation in compatible)
            selected = [observation for observation in compatible
                        if observation["observed_at"] == latest_at]
            outcomes = {observation["outcome"] for observation in selected}
            if len(outcomes) > 1:
                state, reasons = "conflict", ["latest_outcomes_conflict"]
            else:
                state = selected[0]["outcome"]
                if state == "unknown":
                    reasons = ["latest_outcome_unknown"]
        elif stale[identifier]:
            state, reasons = "stale", ["fresh_observation_required"]
            latest_at = max(observation["observed_at"] for observation in stale[identifier])
            selected = [observation for observation in stale[identifier]
                        if observation["observed_at"] == latest_at]
        else:
            state, reasons = "missing", ["compatible_current_observation_missing"]
        rows.append({"id": identifier, "state": state,
                     "observation_ids": sorted(observation["id"] for observation in selected),
                     "considered_observation_ids": considered,
                     "latest_observed_at": latest_at, "reasons": reasons})

    unresolved = {row["id"] for row in rows if row["state"] in NEEDS_OBSERVATION}
    candidates = []
    for probe in request["probes"]:
        covered = sorted(unresolved.intersection(probe["requirement_ids"]))
        if covered:
            candidates.append({"id": probe["id"], "requirement_ids": covered,
                               "coverage_count": len(covered),
                               "estimated_latency_ms": probe["estimated_latency_ms"]})
    candidates.sort(key=lambda item: (
        -item["coverage_count"], item["estimated_latency_ms"] is None,
        item["estimated_latency_ms"] if item["estimated_latency_ms"] is not None else 0,
        item["id"],
    ))
    states = {row["state"] for row in rows}
    status = "blocked" if "fail" in states else (
        "ready" if states == {"pass"} else "needs_observation")
    return {"schema": "parcimonia.observation-review/v1", "status": status,
            "task_id": request["task_id"], "task_revision": request["task_revision"],
            "reviewed_at": now, "requirements": rows,
            "rejected": sorted(rejected, key=lambda item: item["id"]),
            "next_probe": candidates[0] if candidates else None,
            "probe_selection": "coverage_then_known_estimated_latency_then_id",
            "auto_act_allowed": False,
            "evidence_trust": "host_reported_not_independently_attested",
            "measured_savings": None}
