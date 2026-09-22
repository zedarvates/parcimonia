import pytest

from tiberium_ai.signature_corpus import (
    aligned_cases,
    all_cases,
    example_schema,
    paraphrase_cases,
)
from tiberium_ai.task_signature import (
    RuleBasedSignatureBackend,
    SignatureCalibration,
    SignatureCase,
    calibrate_signatures,
)

PREDICTOR_ID = "rule.signature"
PREDICTOR_VERSION = "1"


def calibrate(cases, **overrides):
    arguments = {
        "schema": example_schema(),
        "predictor": RuleBasedSignatureBackend(example_schema()),
        "predictor_id": PREDICTOR_ID,
        "predictor_version": PREDICTOR_VERSION,
    }
    arguments.update(overrides)
    return calibrate_signatures(cases, **arguments)


def as_outcomes(cases, rounds=1):
    """Declare the same cases as captured situations with outcome labels."""
    return tuple(
        SignatureCase(
            f"{case.case_id}-r{round_index}",
            case.prompt,
            case.kind,
            case.fields,
            case.goal,
            situations_origin="captured",
            label_origin="outcome",
        )
        for round_index in range(rounds)
        for case in cases
    )


def covered(report):
    return [entry for entry in report.observations if not entry["abstained"]]


# --- what the authored corpus can and cannot say --------------------------


def test_the_schema_is_an_example_vocabulary_not_the_official_one():
    schema = example_schema()
    assert schema.name == "parcimonia-example"
    assert len(schema.kinds) >= 2
    assert schema.field_names()
    assert schema.goal_names()[-1] == "none"
    assert all(item.hints for item in schema.kinds)
    assert all(item.hints for item in schema.fields)
    assert all(item.hints for item in schema.goals)


def test_every_case_is_authored_and_authored_cases_authorize_nothing():
    for case in all_cases():
        assert case.situations_origin == "authored"
        assert case.label_origin == "authored"
    report = calibrate(all_cases())
    assert report.cases == 24
    assert report.data_origin == "fixture"
    assert report.threshold_authorized is False
    assert report.labeler_id is None
    assert report.independent is True


def test_the_aligned_half_is_perfect_on_its_own_vocabulary():
    report = calibrate(aligned_cases())
    assert report.cases == 12
    assert report.abstained == 0
    assert report.coverage == 1.0
    assert report.kind_agreement == 1.0
    assert report.field_precision == 1.0
    assert report.field_recall == 1.0
    assert report.goal_agreement == 1.0


def test_the_paraphrase_half_exposes_the_rule():
    report = calibrate(paraphrase_cases())
    assert report.cases == 12
    assert report.abstained == 9
    assert report.coverage == pytest.approx(0.25)
    assert report.kind_agreement == 0.0


def test_the_answered_paraphrases_are_accidental_hint_collisions():
    answered = covered(calibrate(paraphrase_cases()))
    assert len(answered) == 3
    assert all(entry["kind"] != entry["expected_kind"] for entry in answered)
    assert {entry["kind"] for entry in answered} == {"format", "verify"}


def test_the_word_before_invents_a_deadline_field():
    answered = covered(calibrate(paraphrase_cases()))
    invented = [
        entry
        for entry in answered
        if entry["fields"] == ["deadline"] and entry["expected_fields"] == []
    ]
    assert len(invented) == 1


def test_aggregating_both_halves_flatters_the_rule():
    aligned = calibrate(aligned_cases())
    paraphrased = calibrate(paraphrase_cases())
    together = calibrate(all_cases())
    assert together.kind_agreement > paraphrased.kind_agreement
    assert together.coverage > paraphrased.coverage
    assert together.kind_agreement < aligned.kind_agreement
    assert together.threshold_authorized is False


# --- provenance: who labelled, and who predicted --------------------------


def test_a_self_labelled_corpus_cannot_authorize():
    self_labelled = as_outcomes(aligned_cases(), rounds=2)
    report = calibrate(self_labelled, labeler_id=PREDICTOR_ID)
    assert report.cases == 24
    assert report.data_origin == "labelled_outcomes"
    assert report.coverage == 1.0
    assert report.kind_agreement == 1.0
    assert report.labeler_id == PREDICTOR_ID
    assert report.independent is False
    assert report.threshold_authorized is False


def test_an_independent_labeller_over_captured_outcomes_authorizes():
    report = calibrate(as_outcomes(aligned_cases(), rounds=2), labeler_id="human-review")
    assert report.data_origin == "labelled_outcomes"
    assert report.independent is True
    assert report.threshold_authorized is True


def test_an_authorized_report_cannot_be_forged_with_its_own_labels():
    with pytest.raises(ValueError, match="labels it produced itself"):
        SignatureCalibration(
            schema_name="parcimonia-example",
            predictor_id=PREDICTOR_ID,
            predictor_version=PREDICTOR_VERSION,
            data_origin="labelled_outcomes",
            cases=40,
            abstained=0,
            coverage=1.0,
            kind_agreement=1.0,
            field_precision=1.0,
            field_recall=1.0,
            goal_agreement=1.0,
            threshold_authorized=True,
            labeler_id=PREDICTOR_ID,
        )


def test_a_model_labelled_corpus_over_authored_situations_stays_a_fixture():
    cases = tuple(
        SignatureCase(
            case.case_id,
            case.prompt,
            case.kind,
            case.fields,
            case.goal,
            label_origin="model",
        )
        for case in aligned_cases()
    )
    report = calibrate(cases, labeler_id="teacher.model")
    assert report.data_origin == "fixture"
    assert report.threshold_authorized is False


def test_a_captured_corpus_with_model_labels_is_not_an_outcome_corpus():
    cases = tuple(
        SignatureCase(
            case.case_id,
            case.prompt,
            case.kind,
            case.fields,
            case.goal,
            situations_origin="captured",
            label_origin="model",
        )
        for case in aligned_cases()
    )
    report = calibrate(cases, labeler_id="teacher.model")
    assert report.data_origin == "fixture"
    assert report.labeler_id == "teacher.model"
    assert report.threshold_authorized is False
