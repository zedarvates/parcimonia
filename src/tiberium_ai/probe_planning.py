"""Advisory test planning over caller-declared hypothesis partitions.

No test is run here. A partition's worst branch describes only its declared
model; it does not establish exhaustive causes, real test quality, probability
or measured information gain. The existing observation reviewer preserves the
supplied report states, including failures. Explicit ``now`` makes this pure
calculation deterministic; otherwise the existing reviewer reads its clock.
"""
from __future__ import annotations

from fractions import Fraction

from .decision_json import canonical_json
from .execution_profiles import digest
from .local_compute import fields, number
from .observation_review import NEEDS_OBSERVATION, review_observations


MAX_INPUT_BYTES = 1024 ** 2
MAX_INPUT_NODES = 65536
MODEL_FIELDS = (
    "schema", "task_id", "task_revision", "revision",
    "observation_request_sha256", "cost_unit", "hypothesis_ids", "probes",
)
PROBE_MODEL_FIELDS = (
    "id", "estimated_cost", "unmodelled_outcome_possible", "outcomes",
)


def _label(value, name):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or not value.isprintable() or not value.strip()):
        raise ValueError(f"{name}: bounded nonempty printable label required")


def _bounded(value):
    # Count serialized occurrences, including shared Python objects and keys,
    # before canonical JSON can expand them. This is a lower byte bound; the
    # final serialization still enforces the complete encoded size below.
    pending = [(value, 0)]
    visited = 0
    minimum_bytes = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        minimum_bytes += 1
        if visited > MAX_INPUT_NODES:
            raise ValueError("probe planning input exceeds the traversal budget")
        if depth > 32:
            raise ValueError("probe planning input is nested too deeply")
        if isinstance(item, str):
            if len(item) > MAX_INPUT_BYTES:
                raise ValueError("probe planning input exceeds 1 MiB")
            try:
                minimum_bytes += len(item.encode("utf-8"))
            except UnicodeError:
                raise ValueError("probe planning input must be finite JSON") from None
        if minimum_bytes > MAX_INPUT_BYTES:
            raise ValueError("probe planning input exceeds 1 MiB")
        if isinstance(item, (dict, list, tuple)):
            if len(item) > 256:
                raise ValueError("probe planning collection exceeds 256 entries")
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth + 1) for child in children)
            if isinstance(item, dict):
                pending.extend((key, depth + 1) for key in item)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            number(item, "input number")
    try:
        encoded = canonical_json(value).encode("utf-8")
    except (TypeError, UnicodeError, ValueError):
        raise ValueError("probe planning input must be finite JSON") from None
    if len(encoded) > MAX_INPUT_BYTES:
        raise ValueError("probe planning input exceeds 1 MiB")


def _ids(value, name, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{name}: invalid list size")
    for identifier in value:
        _label(identifier, name)
    if len(set(value)) != len(value):
        raise ValueError(f"{name}: duplicate label")
    return set(value)


def _validate_model(model, request, request_hash):
    fields(model, MODEL_FIELDS)
    if model["schema"] != "parcimonia.probe-planning-model/v1":
        raise ValueError("unsupported probe planning model schema")
    for name in ("task_id", "task_revision", "revision", "cost_unit"):
        _label(model[name], name)
    if (model["task_id"] != request["task_id"]
            or model["task_revision"] != request["task_revision"]
            or model["observation_request_sha256"] != request_hash):
        raise ValueError("planning model does not bind the exact observation request")
    hypotheses = _ids(model["hypothesis_ids"], "hypothesis IDs", 2, 64)
    if not isinstance(model["probes"], list) or len(model["probes"]) > 32:
        raise ValueError("at most 32 probe models required")
    known_probes = {probe["id"] for probe in request["probes"]}
    models = {}
    for probe in model["probes"]:
        fields(probe, PROBE_MODEL_FIELDS)
        _label(probe["id"], "probe model ID")
        if probe["id"] in models or probe["id"] not in known_probes:
            raise ValueError("probe model IDs must be unique and declared in the request")
        number(probe["estimated_cost"], "estimated cost", optional=True)
        if type(probe["unmodelled_outcome_possible"]) is not bool:
            raise ValueError("unmodelled outcome flag must be a boolean")
        outcomes = probe["outcomes"]
        if not isinstance(outcomes, list) or not 1 <= len(outcomes) <= 64:
            raise ValueError("a probe requires 1..64 declared outcome groups")
        outcome_ids, partition = set(), set()
        for outcome in outcomes:
            fields(outcome, ("id", "hypothesis_ids"))
            _label(outcome["id"], "outcome ID")
            if outcome["id"] in outcome_ids:
                raise ValueError("duplicate outcome ID")
            outcome_ids.add(outcome["id"])
            group = _ids(outcome["hypothesis_ids"], "outcome hypothesis IDs", 1, 64)
            if group - hypotheses or partition.intersection(group):
                raise ValueError("outcome groups must partition the declared hypotheses")
            partition.update(group)
        if partition != hypotheses:
            raise ValueError("outcome partition must cover every declared hypothesis")
        models[probe["id"]] = probe
    return models


def _dominates(left, right):
    # A null in either cost dimension makes these rows incomparable. Identical
    # nulls are not equality evidence, and estimates never become measurements.
    names = ("worst_case_remaining_hypotheses", "estimated_latency_ms", "estimated_cost")
    if any(left[name] is None or right[name] is None for name in names):
        return False
    pairs = [(Fraction(left[name]), Fraction(right[name])) for name in names]
    return all(a <= b for a, b in pairs) and any(a < b for a, b in pairs)


def plan_observation_probes(observation_request, planning_model, *,
                            max_estimated_latency_ms=None,
                            max_estimated_cost=None, now=None):
    """Propose a test or retain Pareto alternatives from a declared model.

    The request is reviewed afresh by ``review_observations``. The model must
    name that exact request's task, revision and canonical SHA-256; it does not
    authenticate its caller or establish that the hypotheses are exhaustive.
    Each modelled probe declares a complete disjoint partition. Its smallest
    elimination *within that declaration* is N minus the largest outcome group.
    A possible unmodelled outcome makes that metric unknown and unselectable.

    Hard caps compare only supplied estimates and refuse unknown estimates.
    Without caps an unknown cost remains incomparable, never a zero cost.
    A unique Pareto row is a proposal; multiple rows need an explicit preference
    outside this function. Existing failure/ready states suppress new proposals.
    There are no model, file, network, reservation, execution or retry calls.
    """
    _bounded({"observation_request": observation_request, "planning_model": planning_model,
              "max_estimated_latency_ms": max_estimated_latency_ms,
              "max_estimated_cost": max_estimated_cost, "now": now})
    number(max_estimated_latency_ms, "estimated latency cap", optional=True)
    number(max_estimated_cost, "estimated cost cap", optional=True)
    observation_review = review_observations(observation_request, now=now)
    request_hash = digest(observation_request)
    models = _validate_model(planning_model, observation_request, request_hash)
    unresolved = {row["id"] for row in observation_review["requirements"]
                  if row["state"] in NEEDS_OBSERVATION}
    count = len(planning_model["hypothesis_ids"])
    candidates = []
    for probe in sorted(observation_request["probes"], key=lambda row: row["id"]):
        model = models.get(probe["id"])
        covered = sorted(unresolved.intersection(probe["requirement_ids"]))
        reasons = []
        if not covered:
            reasons.append("no_unresolved_requirement")
        if model is None:
            reasons.append("probe_model_missing")
        elif model["unmodelled_outcome_possible"]:
            reasons.append("unmodelled_outcome_possible")
        worst_remaining = None
        eliminated = None
        if model is not None and not model["unmodelled_outcome_possible"]:
            worst_remaining = max(len(outcome["hypothesis_ids"]) for outcome in model["outcomes"])
            eliminated = count - worst_remaining
            if eliminated == 0:
                reasons.append("no_declared_discrimination")
        cost = model["estimated_cost"] if model is not None else None
        latency = probe["estimated_latency_ms"]
        for estimate, cap, name in ((cost, max_estimated_cost, "cost"),
                                    (latency, max_estimated_latency_ms, "latency")):
            if cap is not None:
                if estimate is None:
                    reasons.append(name + "_estimate_unknown_under_cap")
                elif Fraction(estimate) > Fraction(cap):
                    reasons.append(name + "_estimate_exceeds_cap")
        if observation_review["status"] == "blocked":
            reasons.append("observation_blocked")
        candidates.append({
            "id": probe["id"], "requirement_ids": covered,
            "estimated_latency_ms": latency, "estimated_cost": cost,
            "unmodelled_outcome_possible": model["unmodelled_outcome_possible"] if model else None,
            "hypothesis_count": count,
            "worst_case_remaining_hypotheses": worst_remaining,
            "worst_case_eliminated_hypotheses": eliminated,
            "selectable": not reasons, "reasons": sorted(reasons),
        })
    eligible = [row for row in candidates if row["selectable"]]
    front = [row["id"] for row in eligible
             if not any(_dominates(other, row) for other in eligible if other is not row)]
    if observation_review["status"] in ("blocked", "ready"):
        status = observation_review["status"]
    else:
        status = "abstained" if not front else "proposed" if len(front) == 1 else "needs_preference"
    selected = next((row for row in candidates if status == "proposed" and row["id"] == front[0]), None)
    result = {
        "schema": "parcimonia.observation-probe-plan/v1", "status": status,
        "task_id": observation_request["task_id"], "task_revision": observation_request["task_revision"],
        "reviewed_at": observation_review["reviewed_at"],
        "observation_request_sha256": request_hash, "planning_model_sha256": digest(planning_model),
        "planning_model_revision": planning_model["revision"],
        "observation_review": observation_review, "observation_review_sha256": digest(observation_review),
        "cost_unit": planning_model["cost_unit"],
        "max_estimated_latency_ms": max_estimated_latency_ms, "max_estimated_cost": max_estimated_cost,
        "candidates": candidates, "frontier_probe_ids": front, "next_probe": selected,
        "selection_method": "declared_worst_branch_and_estimated_latency_cost_pareto",
        "model_trust": "host_declared_not_independently_verified",
        "evidence_trust": observation_review["evidence_trust"],
        "information_gain": "conditional_on_declared_partition_not_measured",
        "auto_act_allowed": False, "reservation_performed": False, "execution_performed": False,
        "measured_savings": None,
    }
    result["report_sha256"] = digest(result)
    return result
