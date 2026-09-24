from tiberium_ai.label_review import LabelOption, review_label_options
from tiberium_ai.signature_backends import VerbFrameSignatureBackend
from tiberium_ai.signature_corpus import example_schema, paraphrase_cases


def test_review_shows_score_sensitivity_without_changing_authored_corpus():
    schema = example_schema()
    cases = paraphrase_cases()
    original = {case.case_id: case.kind for case in cases}
    options = (
        LabelOption("paraphrase-09", "verify", "spelling check as verification"),
        LabelOption("paraphrase-10", "format", "first action in a sequence"),
        LabelOption("paraphrase-11", "format", "first action in a sequence"),
    )
    report = review_label_options(
        cases,
        options,
        schema=schema,
        predictor=VerbFrameSignatureBackend(schema),
        predictor_id="frame",
        predictor_version="1",
    )
    assert report.data_origin == "fixture"
    assert report.decision_owner == "human"
    assert set(report.option_agreements) == {
        "paraphrase-09:verify",
        "paraphrase-10:format",
        "paraphrase-11:format",
    }
    assert {case.case_id: case.kind for case in paraphrase_cases()} == original
    assert all(
        score is not None and score >= report.baseline_kind_agreement
        for score in report.option_agreements.values()
    )
