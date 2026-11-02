"""Deterministic workflow evidence over caller-owned jobs and existing captures.

No agents, tools, jobs, hooks or permissions are created here. Plans are advice;
supplied records are validated for consistency, not certified as independent truth.
The existing semantic review triage remains in shadow mode at its current depth.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import fnmatch
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from ..capture import CapturedRun
from ..contracts import validate_verification_record
from ..measurement import _validate_measurement_record
from ..registry import _reject_constant, _reject_duplicate_keys
from ..verification import hash_input


POLICY = "workflow-review/1"
REVIEW_STATES = {"requested", "running", "completed", "failed", "interrupted",
                 "quota_exhausted", "cancelled", "timed_out"}
PHASES = {"research", "implementation", "verification", "review", "rework", "human"}
_SCOPE = {"task_id", "base_revision", "head_revision", "diff_sha256"}
_SENSITIVE = {
    "authorization": ("*auth*", "*permission*", "*credential*", "*secret*"),
    "persistent_data": ("*migration*", "*.sql"),
    "billing": ("*billing*", "*pricing*", "*payment*", "*quota*"),
    "execution_lifecycle": ("*executor*", "*queue*", "*worktree*", "*lock*"),
}


def _closed(value, fields, name):
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} needs exactly {sorted(fields)}")


def _text(value, name, cap=4096):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > cap:
        raise ValueError(f"invalid {name}")
    return value


def _hash(value, name):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _scope(value):
    _closed(value, _SCOPE, "revision scope")
    _text(value["task_id"], "task id", 200)
    for field in ("base_revision", "head_revision"):
        if not isinstance(value[field], str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value[field]) is None:
            raise ValueError("full revision identities are required")
    _hash(value["diff_sha256"], "diff hash")
    return deepcopy(dict(value))


def _stamp(value, name):
    _text(value, name, 80)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps need an explicit timezone")
    return parsed


def _finite_sum(values):
    try:
        total = math.fsum(values)
    except (OverflowError, ValueError):
        return None
    return total if math.isfinite(total) else None


def plan_workflow_review(request: Mapping[str, Any]) -> dict[str, Any]:
    """Recommend effort from declared impact and deterministic sensitive paths.

    Uncertainty never earns a cheaper review. A focused-check recommendation is
    only for an explicitly low-impact, easily reversible, understood change.
    This does not lower ``review.triage@1``'s effective depth or authorize a merge.
    """
    _closed(request, {"scope", "changed_paths", "impact", "reversibility", "uncertainty"}, "review request")
    scope = _scope(request["scope"])
    paths = request["changed_paths"]
    if not isinstance(paths, (list, tuple)) or not paths or len(paths) > 1000:
        raise ValueError("changed paths must contain 1..1000 explicit paths")
    for path in paths:
        _text(path, "changed path")
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate changed paths")
    if request["impact"] not in {"low", "moderate", "high", "unknown"}:
        raise ValueError("invalid impact")
    if request["reversibility"] not in {"easy", "costly", "unknown"}:
        raise ValueError("invalid reversibility")
    if request["uncertainty"] not in {"low", "high", "unknown"}:
        raise ValueError("invalid uncertainty")
    specialties = sorted(name for name, patterns in _SENSITIVE.items()
                         if any(any(fnmatch.fnmatch(path.casefold(), p) for p in patterns) for path in paths))
    sensitive_paths_detected = bool(specialties)
    if specialties or request["impact"] == "high" or request["reversibility"] == "costly":
        depth = "specialist"
    elif request["impact"] == "low" and request["reversibility"] == "easy" and request["uncertainty"] == "low":
        depth = "focused_checks"
    else:
        depth = "independent"
    if depth == "specialist" and not specialties:
        specialties = ["system_design"]
    reasons = ["sensitive_paths"] if sensitive_paths_detected else []
    reasons += [name + "_" + request[name] for name in ("impact", "reversibility", "uncertainty")]
    payload = {"schema": "workflow-review-plan/1", "policy": POLICY,
               "request": {**deepcopy(dict(request)), "scope": scope, "changed_paths": list(paths)},
               "recommended_review": depth, "required_specialties": specialties,
               "reason_codes": reasons, "mode": "advisory", "auto_act_allowed": False,
               "brief": {"scope": scope,
                         "instruction": "Review the exact diff, intended behavior and raw checks independently. "
                                        "Report verified findings, uncertainty and missing validation; do not change files."},
               "merge_authorized": False}
    return {**payload, "plan_sha256": hash_input(payload)}


def _plan(value):
    if not isinstance(value, Mapping) or not isinstance(value.get("request"), Mapping):
        raise ValueError("a generated review plan is required")
    expected = plan_workflow_review(value["request"])
    if dict(value) != expected:
        raise ValueError("review plan content or policy changed")
    return expected


def summarize_workflow_reviews(plan: Mapping[str, Any], attempts: Sequence[Mapping[str, Any]], *,
                               evidence_root: str | Path | None = None) -> dict[str, Any]:
    """Keep failures and stale reviews visible; a requested review is not done.

    A report on an earlier plan/revision is retained as stale. Completion needs
    an independent declared identity, report reference and hash, and terminal
    timing, and a bounded re-read under an explicit local evidence root. Without
    access to the report a claimed completion stays incomplete. The report text
    is never returned. Model/provider independence is not inferred from names.
    A completed report may contain serious findings: this never declares merge
    readiness or substitutes for validation of its findings.
    """
    plan = _plan(plan)
    root = None if evidence_root is None else Path(evidence_root).resolve(strict=True)
    if root is not None and not root.is_dir():
        raise ValueError("evidence root must be a directory")
    if not isinstance(attempts, (list, tuple)) or len(attempts) > 1000:
        raise ValueError("attempts must be a bounded sequence")
    ids, rows = set(), []
    terminal = REVIEW_STATES - {"requested", "running"}
    for attempt in attempts:
        _closed(attempt, {"attempt_id", "plan_sha256", "reviewer_id", "implementer_id", "specialties",
                          "state", "started_at", "finished_at", "report_ref", "report_sha256"}, "review attempt")
        for field in ("attempt_id", "reviewer_id", "implementer_id"):
            _text(attempt[field], field, 200)
        if attempt["attempt_id"] in ids:
            raise ValueError("duplicate review attempt")
        ids.add(attempt["attempt_id"])
        _hash(attempt["plan_sha256"], "review plan hash")
        if attempt["state"] not in REVIEW_STATES:
            raise ValueError("invalid review state")
        if not isinstance(attempt["specialties"], (list, tuple)) or len(set(attempt["specialties"])) != len(attempt["specialties"]):
            raise ValueError("invalid reviewer specialties")
        for specialty in attempt["specialties"]:
            _text(specialty, "reviewer specialty", 100)
        started = None if attempt["started_at"] is None else _stamp(attempt["started_at"], "start")
        finished = None if attempt["finished_at"] is None else _stamp(attempt["finished_at"], "finish")
        if finished is not None and (started is None or finished < started):
            raise ValueError("review finish precedes its start")
        if attempt["report_ref"] is not None:
            _text(attempt["report_ref"], "report reference")
        if attempt["report_sha256"] is not None:
            _hash(attempt["report_sha256"], "report hash")
        reasons = []
        if attempt["plan_sha256"] != plan["plan_sha256"]:
            reasons.append("stale_plan_or_revision")
        if attempt["state"] == "completed":
            if attempt["reviewer_id"] == attempt["implementer_id"]:
                reasons.append("same_declared_implementer_and_reviewer")
            if attempt["report_ref"] is None or attempt["report_sha256"] is None:
                reasons.append("missing_review_report")
            if started is None or finished is None:
                reasons.append("missing_completion_timing")
            if root is None:
                reasons.append("report_not_reopened")
            elif attempt["report_ref"] is not None and attempt["report_sha256"] is not None:
                try:
                    reference = Path(attempt["report_ref"])
                    if reference.is_absolute() or ".." in reference.parts:
                        raise ValueError("report reference escapes root")
                    path = (root / reference).resolve(strict=True)
                    if not path.is_relative_to(root) or not path.is_file():
                        raise ValueError("report reference escapes root")
                    with path.open("rb") as stream:
                        content = stream.read(1048577)
                    if not content or len(content) > 1048576:
                        reasons.append("empty_or_oversized_report")
                    elif sha256(content).hexdigest() != attempt["report_sha256"]:
                        reasons.append("review_report_hash_mismatch")
                    else:
                        try:
                            review = json.loads(content, object_pairs_hook=_reject_duplicate_keys,
                                                parse_constant=_reject_constant)
                            _closed(review, {"schema", "plan_sha256", "reviewer_id", "summary", "findings", "validation_gaps"}, "review report")
                            if (review["schema"] != "workflow-review-report/1"
                                    or review["plan_sha256"] != attempt["plan_sha256"]
                                    or review["reviewer_id"] != attempt["reviewer_id"]):
                                raise ValueError("review report scope or identity changed")
                            _text(review["summary"], "review summary", 131072)
                            for field in ("findings", "validation_gaps"):
                                if not isinstance(review[field], list) or len(review[field]) > 1000:
                                    raise ValueError("invalid review findings or gaps")
                                for item in review[field]:
                                    _text(item, field, 131072)
                        except (ValueError, TypeError, UnicodeError):
                            reasons.append("review_report_scope_or_content_invalid")
                except (OSError, ValueError):
                    reasons.append("review_report_unavailable")
        elif attempt["state"] in terminal:
            reasons.append(attempt["state"])
        else:
            reasons.append("review_not_completed")
        rows.append({**deepcopy(dict(attempt)), "eligible_completion": not reasons,
                     "reason_codes": reasons})
    completed = [row for row in rows if row["eligible_completion"]]
    covered = {specialty for row in completed for specialty in row["specialties"]}
    missing = sorted(set(plan["required_specialties"]) - covered)
    required = plan["recommended_review"] != "focused_checks"
    done = (bool(completed) and not missing) if required else None
    return {"schema": "workflow-review-status/1", "plan_sha256": plan["plan_sha256"],
            "scope": deepcopy(plan["request"]["scope"]), "review_required": required,
            "review_complete": done, "status": "not_required_by_proposal" if not required else "completed" if done else "incomplete",
            "attempts": rows, "missing_specialties": missing,
            "completed_attempts": len(completed), "independence_certified": False,
            "completion_basis": "exact supplied scope and report bytes; findings are not certified",
            "findings_validated": None, "merge_ready": None, "auto_act_allowed": False}


def capture_workflow_event(captured: CapturedRun, *, event_id: str, phase: str,
                           scope: Mapping[str, Any]) -> dict[str, Any]:
    """Attach an already-performed capture; never execute or retry its operation."""
    if not isinstance(captured, CapturedRun):
        raise TypeError("a CapturedRun is required")
    _text(event_id, "event id", 200)
    if phase not in PHASES:
        raise ValueError("invalid workflow phase")
    scope = _scope(scope)
    measured = deepcopy(captured.measurement)
    _validate_measurement_record(measured)
    if measured["task_id"] != scope["task_id"]:
        raise ValueError("capture belongs to another task")
    verification = None if captured.verification is None else captured.verification.to_record()
    if verification is not None and verification["input_hash"] != hash_input(captured.output):
        raise ValueError("captured output changed after verification")
    return {"schema": "workflow-event/1", "event_id": event_id, "phase": phase,
            "scope": scope, "measurement": measured, "verification": verification}


def summarize_acceptance_cost(scope: Mapping[str, Any], events: Sequence[Mapping[str, Any]], *,
                              accepted_event_id: str | None = None) -> dict[str, Any]:
    """Account for every supplied attempt up to an attributed accepted result.

    Failed attempts and reviews still consume resources. Unknown costs remain
    null; duplicate IDs or reused measurement receipts are rejected. The full
    cost is available only with every phase explicitly covered (including human
    and verification work). A caller may record an explicit zero, never infer it.
    Event timestamps, not list order, define the cutoff. An operation spanning
    the acceptance instant has an unknown partial cost, so it blocks a full
    total. Summed operation latency excludes unrecorded waits and is not wall duration.
    No quality, saving, completion or production claim is authorized here.
    """
    scope = _scope(scope)
    if not isinstance(events, (list, tuple)) or len(events) > 10000:
        raise ValueError("events must be a bounded sequence")
    if accepted_event_id is not None:
        _text(accepted_event_id, "accepted event id", 200)
    ids, receipts, checked = set(), set(), []
    for event in events:
        _closed(event, {"schema", "event_id", "phase", "scope", "measurement", "verification"}, "workflow event")
        if event["schema"] != "workflow-event/1" or event["phase"] not in PHASES:
            raise ValueError("unsupported workflow event")
        _text(event["event_id"], "event id", 200)
        event_scope = _scope(event["scope"])
        if event_scope["task_id"] != scope["task_id"]:
            raise ValueError("event belongs to another task")
        measured = event["measurement"]
        _validate_measurement_record(measured)
        if measured["task_id"] != scope["task_id"]:
            raise ValueError("measurement belongs to another task")
        receipt = hash_input(measured)
        if event["event_id"] in ids or receipt in receipts:
            raise ValueError("duplicate event or reused measurement")
        ids.add(event["event_id"])
        receipts.add(receipt)
        if event["verification"] is not None:
            validate_verification_record(event["verification"])
            if measured["outcome"]["ok"] is not True:
                raise ValueError("failed operation cannot have an output verification")
        checked.append(deepcopy(dict(event)))
    if accepted_event_id is not None and accepted_event_id not in ids:
        raise ValueError("accepted event is missing")
    selected = next((i for i, event in enumerate(checked) if event["event_id"] == accepted_event_id), None)
    acceptance_reasons = []
    if selected is None:
        acceptance_reasons.append("no_accepted_event")
    else:
        event = checked[selected]
        if event["scope"] != scope:
            acceptance_reasons.append("acceptance_on_another_revision")
        if event["verification"] is None or event["verification"]["verdict"] is not True:
            acceptance_reasons.append("acceptance_not_verified")
        if event["phase"] != "verification":
            acceptance_reasons.append("acceptance_is_not_final_verification")
        if event["measurement"]["outcome"]["ok"] is not True:
            acceptance_reasons.append("accepted_operation_failed")
    accepted = not acceptance_reasons
    # An invalid acceptance cannot truncate away later attempts or their costs.
    overlapping, unrepresentable_times = [], []
    if accepted:
        cutoff = _stamp(checked[selected]["measurement"]["measured_at"], "acceptance timestamp")
        horizon = []
        for event in checked:
            finish = _stamp(event["measurement"]["measured_at"], "event timestamp")
            try:
                start = finish - timedelta(milliseconds=event["measurement"]["latency_ms"])
            except OverflowError:
                horizon.append(event)
                unrepresentable_times.append(event["event_id"])
                continue
            if start <= cutoff:
                horizon.append(event)
                if finish > cutoff:
                    overlapping.append(event["event_id"])
    else:
        horizon = checked
    units = {event["measurement"]["cost_unit"] for event in horizon}
    missing = sorted(PHASES - {event["phase"] for event in horizon})
    unknown = [event["event_id"] for event in horizon if event["measurement"]["cost"] is None]
    reasons = list(acceptance_reasons)
    if len(units) != 1:
        reasons.append("mixed_or_missing_cost_units")
    if unknown:
        reasons.append("unknown_event_cost")
    if missing:
        reasons.append("unrecorded_workflow_phases")
    if overlapping:
        reasons.append("event_overlaps_acceptance_time")
    if unrepresentable_times:
        reasons.append("event_time_range_unrepresentable")
    known_by_unit = {unit: _finite_sum(event["measurement"]["cost"] for event in horizon
                              if event["measurement"]["cost_unit"] == unit and event["measurement"]["cost"] is not None)
                     for unit in sorted(units)}
    if any(value is None for value in known_by_unit.values()):
        reasons.append("reported_cost_sum_overflow")
    token_counts = [event["measurement"].get("resources", {}).get("tokens") for event in horizon]
    latency = _finite_sum(event["measurement"]["latency_ms"] for event in horizon)
    return {"schema": "workflow-acceptance-cost/1", "scope": scope,
            "accepted_event_id": accepted_event_id, "acceptance_status": "recorded_verified" if accepted else "unverified",
            "acceptance_reason_codes": acceptance_reasons, "events_counted": len(horizon),
            "events_after_acceptance": len(checked) - len(horizon),
            "events_overlapping_acceptance": overlapping,
            "events_with_unrepresentable_time_ranges": unrepresentable_times,
            "failed_attempts": sum(event["measurement"]["outcome"]["ok"] is not True for event in horizon),
            "rework_events": sum(event["phase"] == "rework" for event in horizon),
            "known_reported_cost_by_unit": known_by_unit,
            "total_cost_until_acceptance": next(iter(known_by_unit.values())) if not reasons else None,
            "cost_unit": next(iter(units)) if len(units) == 1 else None,
            "unknown_cost_event_ids": unknown, "missing_phases": missing,
            "known_reported_tokens": sum(value for value in token_counts if value is not None),
            "tokens_until_acceptance": sum(token_counts) if accepted and not missing and not overlapping and not unrepresentable_times and all(value is not None for value in token_counts) else None,
            "summed_operation_latency_ms": latency,
            "latency_sum_status": "known" if latency is not None else "overflow",
            "wall_elapsed_ms": None, "reason_codes": reasons,
            "record_scope": "caller-supplied captures; unrecorded work and waiting time remain unknown",
            "claim_allowed": False, "auto_act_allowed": False}
