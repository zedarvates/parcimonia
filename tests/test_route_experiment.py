from tiberium_ai.route_experiment import (
    ArmAvailability,
    ExperimentArm,
    ExperimentPlan,
    PairedOutcome,
    assess_experiment,
)


def _plan(availability=ArmAvailability.READY):
    return ExperimentPlan(
        corpus_id="private-heldout/1",
        task_ids=("t1", "t2"),
        baseline_arm_id="llm",
        arms=(
            ExperimentArm("llm", ("llm", "verify"), ArmAvailability.READY, "baseline", "1"),
            ExperimentArm(
                "cheap",
                ("rule", "knn", "typed_judgment", "tool_emit", "verify"),
                availability,
                "local-stack" if availability is ArmAvailability.READY else None,
                "1" if availability is ArmAvailability.READY else None,
            ),
        ),
    )


def _outcomes(candidate_cost=1.0, candidate_verified=True):
    return (
        PairedOutcome("t1", "llm", True, 100, 2.0, True, "labelled_outcomes", "exact", "1"),
        PairedOutcome("t1", "cheap", candidate_verified, 80, candidate_cost, True, "labelled_outcomes", "exact", "1"),
        PairedOutcome("t2", "llm", True, 100, 2.0, True, "labelled_outcomes", "exact", "1"),
        PairedOutcome("t2", "cheap", True, 80, candidate_cost, True, "labelled_outcomes", "exact", "1"),
    )


def test_missing_backends_cannot_get_fabricated_benchmark_result():
    report = assess_experiment(_plan(ArmAvailability.UNAVAILABLE))
    assert report.claim_allowed is False
    assert report.measured_pairs == 0
    assert "arm_unavailable" in report.reason_codes
    assert "missing_paired_outcomes" in report.reason_codes


def test_fixture_and_verification_failure_block_claim():
    outcomes = list(_outcomes(candidate_verified=False))
    outcomes[1] = PairedOutcome("t1", "cheap", False, 80, 1.0, True, "fixture", "exact", "1")
    report = assess_experiment(_plan(), outcomes)
    assert report.claim_allowed is False
    assert "unmeasured_or_fixture" in report.reason_codes
    assert "verification_failure" in report.reason_codes


def test_complete_caller_reported_pairs_remain_advisory():
    good = assess_experiment(_plan(), _outcomes())
    assert good.comparable is True
    assert good.claim_allowed is False
    assert good.estimated_cost_improvement is True
    assert "caller_reported_only" in good.reason_codes
    assert good.measured_pairs == good.required_pairs == 4

    costly = assess_experiment(_plan(), _outcomes(candidate_cost=3.0))
    assert costly.comparable is True
    assert costly.claim_allowed is False
    assert costly.estimated_cost_improvement is False
    assert costly.reason_codes == ("no_total_cost_improvement", "caller_reported_only")


def test_missing_cost_and_one_missing_pair_are_explicit():
    outcomes = list(_outcomes())[:-1]
    outcomes[1] = PairedOutcome("t1", "cheap", True, 80, None, True, "labelled_outcomes", "exact", "1")
    report = assess_experiment(_plan(), outcomes)
    assert report.comparable is False
    assert "incomplete_cost" in report.reason_codes
    assert "missing_paired_outcomes" in report.reason_codes


def test_verifier_identity_must_match_on_both_routes():
    outcomes = list(_outcomes())
    outcomes[1] = PairedOutcome("t1", "cheap", True, 80, 1.0, True, "labelled_outcomes", "other", "1")
    report = assess_experiment(_plan(), outcomes)
    assert report.claim_allowed is False
    assert "verifier_mismatch" in report.reason_codes
