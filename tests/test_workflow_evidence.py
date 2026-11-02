from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

import pytest

from tiberium_ai.agent_recipes.__main__ import main
from tiberium_ai.agent_recipes.workflow import (
    PHASES, capture_workflow_event, plan_workflow_review,
    summarize_acceptance_cost, summarize_workflow_reviews,
)
from tiberium_ai.capture import capture_run
from tiberium_ai.measurement import Environment
from tiberium_ai.resources import ResourceVector
from tiberium_ai.verification import VerifierRegistry


def scope(head="b" * 40):
    return {"task_id": "WF-001", "base_revision": "a" * 40,
            "head_revision": head, "diff_sha256": "c" * 64}


def request(**changes):
    return {"scope": scope(), "changed_paths": ["src/format.py"],
            "impact": "moderate", "reversibility": "easy", "uncertainty": "low", **changes}


def attempt(plan, **changes):
    return {"attempt_id": "review-1", "plan_sha256": plan["plan_sha256"],
            "reviewer_id": "reviewer", "implementer_id": "implementer",
            "specialties": [], "state": "completed",
            "started_at": "2026-11-02T12:00:00Z", "finished_at": "2026-11-02T12:01:00Z",
            "report_ref": "review.json", "report_sha256": sha256(review_bytes(plan)).hexdigest(), **changes}


def review_bytes(plan):
    return json.dumps({"schema": "workflow-review-report/1", "plan_sha256": plan["plan_sha256"],
                       "reviewer_id": "reviewer", "summary": "Review finished.",
                       "findings": ["Verified finding: edge case remains."], "validation_gaps": []}).encode()


def report(root, plan=None):
    (root / "review.json").write_bytes(review_bytes(plan or plan_workflow_review(request())))


def event(event_id, phase, *, cost=1, accepted=False, failed=False, revision=None, unit="USD", tokens=2):
    registry = VerifierRegistry()
    registry.register("workflow.result", "1", lambda value: value == "accepted")
    ticks = iter([0.0, 0.01])
    finish = datetime(2026, 11, 2, 12, tzinfo=timezone.utc) + timedelta(seconds={
        "research": 0, "implementation": 1, "review": 2, "rework": 3, "human": 4, "verify": 5, "after": 6}.get(event_id, 0))
    def operation():
        if failed:
            raise RuntimeError("private error")
        return "accepted" if accepted else "candidate"
    captured = capture_run(task_id="WF-001", route_id=event_id, run=operation,
        verifier_id="workflow.result", verifier_version="1", registry=registry,
        cost_unit=unit, cost=cost, environment=Environment("test"),
        clock=lambda: next(ticks), now=lambda: finish.isoformat(),
        resources=ResourceVector(tokens=tokens))
    return capture_workflow_event(captured, event_id=event_id, phase=phase,
                                  scope=scope() if revision is None else scope(revision))


def complete_events():
    return [event("research", "research", cost=2),
            event("implementation", "implementation", cost=3, failed=True),
            event("review", "review", cost=4), event("rework", "rework", cost=5),
            event("human", "human", cost=0),
            event("verify", "verification", cost=1, accepted=True)]


def test_review_plan_keeps_unknowns_expensive_and_is_advisory():
    assert plan_workflow_review(request(impact="low"))["recommended_review"] == "focused_checks"
    assert plan_workflow_review(request(impact="low", uncertainty="unknown"))["recommended_review"] == "independent"
    plan = plan_workflow_review(request(changed_paths=["src/auth.py"]))
    assert plan["recommended_review"] == "specialist" and plan["required_specialties"] == ["authorization"]
    assert not plan["auto_act_allowed"] and not plan["merge_authorized"]
    assert plan_workflow_review(request(impact="high"))["required_specialties"] == ["system_design"]
    assert "sensitive_paths" not in plan_workflow_review(request(impact="high"))["reason_codes"]


@pytest.mark.parametrize("mutation", [
    {"scope": scope("main")}, {"changed_paths": []}, {"changed_paths": ["same", "same"]},
    {"impact": "tiny"}, {"uncertainty": "certain"}, {"reversibility": "guaranteed"},
])
def test_review_plan_rejects_unbounded_or_ambiguous_inputs(mutation):
    with pytest.raises(ValueError):
        plan_workflow_review(request(**mutation))


def test_requested_quota_and_unread_completion_never_become_completed(tmp_path):
    plan = plan_workflow_review(request())
    attempts = [attempt(plan, attempt_id="asked", state="requested", started_at=None,
                        finished_at=None, report_ref=None, report_sha256=None),
                attempt(plan, attempt_id="quota", state="quota_exhausted", report_ref=None, report_sha256=None),
                attempt(plan)]
    result = summarize_workflow_reviews(plan, attempts)
    assert result["status"] == "incomplete" and not result["review_complete"]
    assert result["completed_attempts"] == 0
    assert "quota_exhausted" in result["attempts"][1]["reason_codes"]
    assert "report_not_reopened" in result["attempts"][2]["reason_codes"]


def test_review_completed_only_after_exact_report_reopened_and_findings_stay_unknown(tmp_path):
    report(tmp_path)
    plan = plan_workflow_review(request())
    result = summarize_workflow_reviews(plan, [attempt(plan)], evidence_root=tmp_path)
    assert result["review_complete"] is True and result["completed_attempts"] == 1
    assert result["findings_validated"] is None and result["merge_ready"] is None
    assert not result["independence_certified"] and not result["auto_act_allowed"]
    assert "Verified finding" not in json.dumps(result)
    (tmp_path / "review.json").write_bytes(b"changed report")
    result = summarize_workflow_reviews(plan, [attempt(plan)], evidence_root=tmp_path)
    assert not result["review_complete"]
    assert "review_report_hash_mismatch" in result["attempts"][0]["reason_codes"]


@pytest.mark.parametrize("changes,reason", [
    ({"reviewer_id": "implementer"}, "same_declared_implementer_and_reviewer"),
    ({"report_sha256": None}, "missing_review_report"),
    ({"finished_at": None}, "missing_completion_timing"),
    ({"report_ref": "../outside.txt"}, "review_report_unavailable"),
])
def test_incomplete_review_conditions_are_preserved(tmp_path, changes, reason):
    report(tmp_path)
    plan = plan_workflow_review(request())
    result = summarize_workflow_reviews(plan, [attempt(plan, **changes)], evidence_root=tmp_path)
    assert not result["review_complete"]
    assert reason in result["attempts"][0]["reason_codes"]


def test_old_revision_and_same_report_cannot_satisfy_new_review(tmp_path):
    report(tmp_path)
    old = plan_workflow_review(request())
    current = plan_workflow_review(request(scope=scope("d" * 40)))
    result = summarize_workflow_reviews(current, [attempt(old)], evidence_root=tmp_path)
    assert not result["review_complete"]
    assert result["attempts"][0]["reason_codes"] == ["stale_plan_or_revision"]


def test_specialist_plan_needs_explicit_coverage_and_no_plan_edit(tmp_path):
    plan = plan_workflow_review(request(changed_paths=["src/auth.py", "schema.sql"]))
    report(tmp_path, plan)
    result = summarize_workflow_reviews(plan, [attempt(plan, specialties=["authorization"])], evidence_root=tmp_path)
    assert not result["review_complete"] and result["missing_specialties"] == ["persistent_data"]
    forged = deepcopy(plan)
    forged["recommended_review"] = "focused_checks"
    with pytest.raises(ValueError, match="changed"):
        summarize_workflow_reviews(forged, [])
    with pytest.raises(ValueError, match="duplicate"):
        summarize_workflow_reviews(plan, [attempt(plan), attempt(plan)])


def test_cost_until_acceptance_includes_failed_work_rework_review_and_human():
    result = summarize_acceptance_cost(scope(), complete_events(), accepted_event_id="verify")
    assert result["acceptance_status"] == "recorded_verified"
    assert result["total_cost_until_acceptance"] == 15
    assert result["failed_attempts"] == 1 and result["rework_events"] == 1
    assert result["tokens_until_acceptance"] == 12
    assert result["wall_elapsed_ms"] is None
    assert not result["claim_allowed"]


def test_unknown_cost_and_missing_phases_never_become_zero():
    events = complete_events()
    events[1]["measurement"]["cost"] = None
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="verify")
    assert result["total_cost_until_acceptance"] is None
    assert result["tokens_until_acceptance"] == 12
    assert result["unknown_cost_event_ids"] == ["implementation"]
    assert result["known_reported_cost_by_unit"] == {"USD": 12}
    result = summarize_acceptance_cost(scope(), [events[-1]], accepted_event_id="verify")
    assert result["total_cost_until_acceptance"] is None
    assert set(result["missing_phases"]) == PHASES - {"verification"}


def test_mixed_currency_is_never_added_or_converted():
    events = complete_events()
    events[1]["measurement"]["cost_unit"] = "EUR"
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="verify")
    assert result["total_cost_until_acceptance"] is None and result["cost_unit"] is None
    assert result["known_reported_cost_by_unit"] == {"EUR": 3, "USD": 12}


def test_duplicate_receipt_cannot_double_count_under_another_event_id():
    events = complete_events()
    clone = deepcopy(events[0])
    clone["event_id"] = "different-id"
    with pytest.raises(ValueError, match="reused measurement"):
        summarize_acceptance_cost(scope(), [*events, clone], accepted_event_id="verify")


def test_acceptance_must_match_current_revision_and_true_verdict_and_cannot_hide_costs():
    events = complete_events()
    events[-1]["scope"] = scope("d" * 40)
    events.append(event("after", "rework", cost=9))
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="verify")
    assert result["acceptance_status"] == "unverified" and result["events_counted"] == 7
    assert result["known_reported_cost_by_unit"] == {"USD": 24}
    assert "acceptance_on_another_revision" in result["acceptance_reason_codes"]
    events[-2]["scope"] = scope()
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="verify")
    assert result["events_after_acceptance"] == 1 and result["total_cost_until_acceptance"] == 15
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="after")
    assert result["total_cost_until_acceptance"] is None
    assert "acceptance_not_verified" in result["acceptance_reason_codes"]


def test_cost_cutoff_uses_timestamps_even_when_list_is_reordered():
    events = complete_events()
    events = [events[-1], *events[:-1]]
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="verify")
    assert result["events_counted"] == 6 and result["total_cost_until_acceptance"] == 15
    events.append(event("after", "rework", cost=9))
    events[-1]["measurement"]["latency_ms"] = 2000
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="verify")
    assert result["events_overlapping_acceptance"] == ["after"]
    assert result["known_reported_cost_by_unit"] == {"USD": 24}
    assert result["total_cost_until_acceptance"] is None
    assert result["tokens_until_acceptance"] is None


def test_verified_intermediate_output_is_not_final_acceptance():
    events = complete_events()
    events[-1]["phase"] = "research"
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="verify")
    assert "acceptance_is_not_final_verification" in result["acceptance_reason_codes"]


def test_finite_inputs_whose_sum_overflows_remain_json_serializable_unknowns():
    events = complete_events()
    events[0]["measurement"]["cost"] = 1e308
    events[1]["measurement"]["cost"] = 1e308
    events[0]["measurement"]["latency_ms"] = 1e308
    events[1]["measurement"]["latency_ms"] = 1e308
    result = summarize_acceptance_cost(scope(), events, accepted_event_id="verify")
    assert result["total_cost_until_acceptance"] is None
    assert result["known_reported_cost_by_unit"] == {"USD": None}
    assert result["tokens_until_acceptance"] is None
    assert result["summed_operation_latency_ms"] is None
    assert "reported_cost_sum_overflow" in result["reason_codes"]
    json.dumps(result, allow_nan=False)


def test_unrelated_report_with_matching_file_hash_cannot_complete_review(tmp_path):
    plan = plan_workflow_review(request())
    other = plan_workflow_review(request(scope=scope("d" * 40)))
    report(tmp_path, other)
    supplied = attempt(plan, report_sha256=sha256(review_bytes(other)).hexdigest())
    result = summarize_workflow_reviews(plan, [supplied], evidence_root=tmp_path)
    assert not result["review_complete"]
    assert "review_report_scope_or_content_invalid" in result["attempts"][0]["reason_codes"]


def test_failed_and_pending_task_cannot_claim_accepted_cost():
    result = summarize_acceptance_cost(scope(), complete_events())
    assert result["total_cost_until_acceptance"] is None
    assert result["acceptance_status"] == "unverified"
    with pytest.raises(ValueError, match="missing"):
        summarize_acceptance_cost(scope(), [], accepted_event_id="missing")


def test_capture_attachment_rejects_output_mutation_and_cross_task():
    registry = VerifierRegistry()
    registry.register("v", "1", lambda value: True)
    value = {"result": "good"}
    times = iter([0, 1])
    captured = capture_run(task_id="WF-001", route_id="candidate", run=lambda: value,
        verifier_id="v", verifier_version="1", registry=registry, cost_unit="USD", cost=0,
        environment=Environment("test"), clock=lambda: next(times))
    value["result"] = "changed"
    with pytest.raises(ValueError, match="changed"):
        capture_workflow_event(captured, event_id="mutated", phase="verification", scope=scope())
    other = {**scope(), "task_id": "other"}
    with pytest.raises(ValueError, match="another task"):
        capture_workflow_event(captured, event_id="mutated", phase="verification", scope=other)


def test_cli_commands_are_wired_without_model_calls(tmp_path, capsys):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request()), encoding="utf-8")
    assert main(["review-plan", "--input", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["calls"] == []
    plan = result["result"]
    path.write_text(json.dumps({"plan": plan, "attempts": []}), encoding="utf-8")
    assert main(["review-status", "--input", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["calls"] == [] and result["result"]["status"] == "incomplete"
    path.write_text(json.dumps({"scope": scope(), "events": complete_events(), "accepted_event_id": "verify"}), encoding="utf-8")
    assert main(["acceptance-cost", "--input", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["calls"] == [] and result["result"]["total_cost_until_acceptance"] == 15
