import json

import pytest

from tiberium_ai.task_signature import (
    ABSTAIN_LOW_KIND,
    NO_GOAL,
    DeclaredItem,
    RuleBasedSignatureBackend,
    SignatureCalibration,
    SignatureCase,
    SignatureSchema,
    TaskSignature,
    calibrate_signatures,
    predict_signature,
    signature_questions,
)

PREDICTOR = {"predictor_id": "rule.signature", "predictor_version": "1"}


def schema():
    return SignatureSchema(
        name="parcimonia",
        kinds=(
            DeclaredItem("extract", ("extract", "parse")),
            DeclaredItem("format", ("format", "tidy")),
            DeclaredItem("decide", ("choose", "select")),
        ),
        capabilities=(
            DeclaredItem("route.knn", ("knn", "similar")),
            DeclaredItem("route.browser", ("browser", "web page")),
        ),
        fields=(
            DeclaredItem("path", ("file", "path")),
            DeclaredItem("schema", ("schema", "fields")),
            DeclaredItem("deadline", ("deadline", "due by")),
        ),
        goals=(DeclaredItem("GOAL-PARCIMONIA", ("parcimonia", "routing")),),
    )


def backend(made=None):
    return RuleBasedSignatureBackend(made or schema())


def predict(prompt, made=None):
    active = made or schema()
    return predict_signature(
        active,
        prompt,
        predictor=RuleBasedSignatureBackend(active),
        **PREDICTOR,
    )


def labelled_corpus(count=20, made=None):
    # kind name, kind hint, field hint, field name: the prompt carries the hints,
    # the expectation carries the declared names.
    rows = (
        ("extract", "extract", "file", "path"),
        ("format", "format", "schema", "schema"),
        ("decide", "choose", "deadline", "deadline"),
    )
    cases = []
    for index in range(count):
        kind, kind_hint, field_hint, field_name = rows[index % len(rows)]
        cases.append(
            SignatureCase(
                case_id=f"case-{index:03d}",
                prompt=f"{kind_hint} the {field_hint} item number {index}",
                kind=kind,
                fields=(field_name,),
            )
        )
    return tuple(cases)


def captured_corpus(count=20):
    """The same prompts, declared as captured situations with outcome labels.

    This exercises the gate's arithmetic and the provenance rule, not a claim
    about the world: the situations in this test are still written here, which
    is exactly why the fixture version of the same corpus cannot authorize.
    """
    return tuple(
        SignatureCase(
            case.case_id,
            case.prompt,
            case.kind,
            case.fields,
            case.goal,
            situations_origin="captured",
            label_origin="outcome",
        )
        for case in labelled_corpus(count)
    )


# --- declared vocabulary --------------------------------------------------


def test_declared_hints_are_lowercase_and_nonempty():
    with pytest.raises(ValueError, match="lowercase"):
        DeclaredItem("path", ("File",))
    with pytest.raises(ValueError, match="nonempty, trimmed"):
        DeclaredItem("path", ("  ",))
    with pytest.raises(ValueError, match="nonempty, trimmed"):
        DeclaredItem("")
    assert DeclaredItem("path", ["file"]).hints == ("file",)


def test_a_schema_needs_two_kinds_and_refuses_a_wider_choice():
    with pytest.raises(ValueError, match="at least 2"):
        SignatureSchema(name="s", kinds=(DeclaredItem("only"),))
    with pytest.raises(ValueError, match="capped at 20"):
        SignatureSchema(
            name="s", kinds=tuple(DeclaredItem(f"k{index}") for index in range(21))
        )


def test_the_no_goal_option_cannot_be_a_declared_goal():
    with pytest.raises(ValueError, match="reserved"):
        SignatureSchema(
            name="s",
            kinds=(DeclaredItem("a"), DeclaredItem("b")),
            goals=(DeclaredItem(NO_GOAL),),
        )


def test_duplicate_names_and_bad_thresholds_are_refused():
    with pytest.raises(ValueError, match="must not repeat"):
        SignatureSchema(
            name="s", kinds=(DeclaredItem("a"), DeclaredItem("a"))
        )
    with pytest.raises(ValueError, match="min_kind_confidence"):
        SignatureSchema(
            name="s",
            kinds=(DeclaredItem("a"), DeclaredItem("b")),
            min_kind_confidence=1.5,
        )


def test_questions_follow_the_reflex_contract():
    questions = signature_questions(schema())
    assert [question.name for question in questions] == [
        "kind",
        "capability.route.knn",
        "capability.route.browser",
        "field.path",
        "field.schema",
        "field.deadline",
        "goal",
    ]
    assert questions[0].kind.value == "choice"
    assert questions[1].kind.value == "noul"
    assert list(questions[-1].option_keys) == ["GOAL-PARCIMONIA", NO_GOAL]


def test_no_goal_question_is_built_without_declared_goals():
    minimal = SignatureSchema(
        name="s", kinds=(DeclaredItem("a"), DeclaredItem("b"))
    )
    assert [question.name for question in signature_questions(minimal)] == ["kind"]


# --- the deterministic baseline ------------------------------------------


def test_a_matching_prompt_yields_a_determined_signature():
    signature = predict("Parse this file and return its schema")
    assert signature.kind == "extract"
    assert signature.kind_confidence == 1.0
    assert signature.fields == ("path", "schema")
    assert signature.capabilities == ()
    assert signature.goal is None
    assert signature.abstained is False
    assert signature.reason_code is None


def test_an_unmatched_prompt_abstains_instead_of_defaulting():
    signature = predict("hello there")
    assert signature.abstained is True
    assert signature.kind is None
    assert signature.reason_code == ABSTAIN_LOW_KIND
    assert signature.kind_confidence is not None
    assert signature.kind_confidence < 0.9


def test_an_ambiguous_prompt_abstains_too():
    signature = predict("parse and tidy this")
    assert signature.abstained is True
    assert signature.kind_confidence == 0.5


def test_capabilities_and_goals_are_matched_without_being_invented():
    signature = predict("find a similar case for the routing work")
    assert signature.capabilities == ("route.knn",)
    assert signature.goal == "GOAL-PARCIMONIA"
    assert signature.goal_confidence == 1.0
    assert signature.kind is None


def test_an_ambiguous_goal_is_dropped_rather_than_guessed():
    made = SignatureSchema(
        name="s",
        kinds=(DeclaredItem("a", ("alpha",)), DeclaredItem("b", ("beta",))),
        goals=(
            DeclaredItem("GOAL-A", ("shared",)),
            DeclaredItem("GOAL-B", ("shared",)),
        ),
    )
    signature = predict("beta on a shared item", made)
    assert signature.kind == "b"
    assert signature.goal is None
    assert signature.goal_confidence == 0.5


def test_a_field_without_hints_is_never_selected():
    made = SignatureSchema(
        name="s",
        kinds=(DeclaredItem("a", ("alpha",)), DeclaredItem("b", ("beta",))),
        fields=(DeclaredItem("silent"), DeclaredItem("loud", ("loud",))),
    )
    signature = predict("alpha and loud", made)
    assert signature.fields == ("loud",)
    assert signature.field_scores["silent"] == 0.0


def test_a_non_latin_prompt_is_not_refused_by_the_rule_backend():
    signature = predict("សួស្តី extract the path")
    assert signature.kind == "extract"
    assert backend().latin_only is False


def test_the_backend_refuses_a_question_it_has_no_item_for():
    from tiberium_ai.reflex import ReflexKind, ReflexQuestion

    stray = ReflexQuestion("field.unknown", ReflexKind.NOUL, "Unknown field?")
    with pytest.raises(KeyError, match="no declared item"):
        backend().evaluate("text", (stray,))


# --- provenance and refusal ----------------------------------------------


def test_the_provenance_is_required_and_carried():
    with pytest.raises(ValueError, match="predictor_id"):
        predict_signature(
            schema(),
            "extract the path",
            predictor=backend(),
            predictor_id=" ",
            predictor_version="1",
        )
    with pytest.raises(ValueError, match="data_origin"):
        predict_signature(
            schema(),
            "extract the path",
            predictor=backend(),
            predictor_id="rule.signature",
            predictor_version="1",
            data_origin="invented",
        )
    signature = predict("extract the path")
    record = signature.to_record()
    assert record["predictor"] == PREDICTOR
    assert record["data_origin"] == "fixture"
    assert record["auto_act_allowed"] is False


def test_the_record_keeps_a_hash_and_never_the_prompt():
    prompt = "extract the deadline for the payroll file"
    signature = predict(prompt)
    payload = json.dumps(signature.to_record())
    assert "payroll" not in payload
    assert len(signature.prompt_hash) == 64


def test_a_predictor_must_expose_evaluate():
    with pytest.raises(TypeError, match="evaluate"):
        predict_signature(
            schema(),
            "extract the path",
            predictor=object(),
            **PREDICTOR,
        )


def test_an_empty_prompt_is_refused():
    with pytest.raises(ValueError, match="nonempty string"):
        predict("   ")


def test_a_signature_cannot_claim_a_kind_while_abstaining():
    signature = predict("extract the path")
    with pytest.raises(ValueError, match="abstained signature"):
        TaskSignature(
            schema_name=signature.schema_name,
            prompt_hash=signature.prompt_hash,
            kind="extract",
            kind_confidence=0.1,
            capabilities=(),
            capability_scores={},
            fields=(),
            field_scores={},
            goal=None,
            goal_confidence=None,
            abstained=True,
            reason_code=ABSTAIN_LOW_KIND,
            predictor_id="rule.signature",
            predictor_version="1",
            data_origin="fixture",
        )


def test_a_selected_name_without_a_score_is_refused():
    signature = predict("extract the path")
    with pytest.raises(ValueError, match="every selected name is scored"):
        TaskSignature(
            schema_name=signature.schema_name,
            prompt_hash=signature.prompt_hash,
            kind="extract",
            kind_confidence=1.0,
            capabilities=(),
            capability_scores={},
            fields=("path",),
            field_scores={},
            goal=None,
            goal_confidence=None,
            abstained=False,
            reason_code=None,
            predictor_id="rule.signature",
            predictor_version="1",
            data_origin="fixture",
        )


# --- calibration ---------------------------------------------------------


def test_a_perfect_fixture_corpus_still_cannot_authorize():
    report = calibrate_signatures(
        labelled_corpus(),
        schema=schema(),
        predictor=backend(),
        **PREDICTOR,
    )
    assert report.coverage == 1.0
    assert report.kind_agreement == 1.0
    assert report.field_precision == 1.0
    assert report.field_recall == 1.0
    assert report.threshold_authorized is False
    assert report.data_origin == "fixture"


def test_the_same_numbers_on_labelled_outcomes_authorize():
    report = calibrate_signatures(
        captured_corpus(),
        schema=schema(),
        predictor=backend(),
        **PREDICTOR,
    )
    assert report.threshold_authorized is True
    assert report.determinate is True
    assert report.data_origin == "labelled_outcomes"


def test_too_few_labelled_cases_do_not_authorize():
    report = calibrate_signatures(
        captured_corpus(count=5),
        schema=schema(),
        predictor=backend(),
        **PREDICTOR,
    )
    assert report.cases == 5
    assert report.threshold_authorized is False


def test_an_authorized_snapshot_cannot_be_forged_from_fixtures():
    with pytest.raises(ValueError, match="only labelled outcomes"):
        SignatureCalibration(
            schema_name="parcimonia",
            predictor_id="rule.signature",
            predictor_version="1",
            data_origin="fixture",
            cases=40,
            abstained=0,
            coverage=1.0,
            kind_agreement=1.0,
            field_precision=1.0,
            field_recall=1.0,
            goal_agreement=None,
            threshold_authorized=True,
        )


def test_coverage_and_agreement_are_reported_separately():
    cases = (
        SignatureCase("c1", "extract the path", "extract", ("path",)),
        SignatureCase("c2", "hello there", "decide"),
        SignatureCase("c3", "tidy the schema", "format", ("schema",), "GOAL-PARCIMONIA"),
    )
    report = calibrate_signatures(
        cases, schema=schema(), predictor=backend(), **PREDICTOR
    )
    assert report.cases == 3
    assert report.abstained == 1
    assert report.coverage == pytest.approx(2 / 3)
    assert report.kind_agreement == 1.0
    assert report.field_precision == 1.0
    assert report.field_recall == 1.0
    assert report.goal_agreement == 0.0
    assert report.observations[1]["abstained"] is True


def test_a_wrong_kind_lowers_agreement_without_hiding_coverage():
    cases = (
        SignatureCase("c1", "extract the path", "decide", ("path",)),
        SignatureCase("c2", "tidy the schema", "format", ("schema",)),
    )
    report = calibrate_signatures(
        cases, schema=schema(), predictor=backend(), **PREDICTOR
    )
    assert report.coverage == 1.0
    assert report.kind_agreement == 0.5


def test_a_corpus_naming_undeclared_things_is_refused():
    with pytest.raises(ValueError, match="undeclared kind"):
        calibrate_signatures(
            (SignatureCase("c1", "extract the path", "unknown"),),
            schema=schema(),
            predictor=backend(),
            **PREDICTOR,
        )
    with pytest.raises(ValueError, match="undeclared field"):
        calibrate_signatures(
            (SignatureCase("c1", "extract the path", "extract", ("missing",)),),
            schema=schema(),
            predictor=backend(),
            **PREDICTOR,
        )
    with pytest.raises(ValueError, match="undeclared goal"):
        calibrate_signatures(
            (SignatureCase("c1", "extract the path", "extract", (), "GOAL-OTHER"),),
            schema=schema(),
            predictor=backend(),
            **PREDICTOR,
        )


def test_an_empty_or_duplicated_corpus_is_refused():
    with pytest.raises(ValueError, match="at least one case"):
        calibrate_signatures(
            (), schema=schema(), predictor=backend(), **PREDICTOR
        )
    with pytest.raises(ValueError, match="duplicate case ids"):
        calibrate_signatures(
            (
                SignatureCase("c1", "extract the path", "extract", ("path",)),
                SignatureCase("c1", "tidy the schema", "format", ("schema",)),
            ),
            schema=schema(),
            predictor=backend(),
            **PREDICTOR,
        )
