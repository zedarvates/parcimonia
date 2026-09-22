import pytest

from tiberium_ai.public_corpus import (
    CATEGORY_TO_KIND,
    PUBLIC_FIELD,
    PUBLIC_KIND_HINTS,
    cases_from_rows,
    public_schema,
    public_split,
)
from tiberium_ai.signature_backends import VerbFrameSignatureBackend
from tiberium_ai.task_signature import (
    SignatureCase,
    calibrate_signatures,
)


def row(category, instruction="do the thing", context_present=False):
    return {
        "category": category,
        "instruction": instruction,
        "context_present": context_present,
    }


def test_the_declared_kinds_cover_every_mapped_category():
    schema = public_schema()
    declared = {item.name for item in schema.kinds}
    assert set(PUBLIC_KIND_HINTS) == declared
    assert set(CATEGORY_TO_KIND.values()) <= declared
    assert schema.field_names() == (PUBLIC_FIELD,)
    assert schema.goals == ()


def test_the_mapping_is_closed_over_the_categories_we_observed():
    observed = {
        "closed_qa",
        "classification",
        "open_qa",
        "information_extraction",
        "brainstorming",
        "general_qa",
        "summarization",
        "creative_writing",
    }
    assert observed <= set(CATEGORY_TO_KIND)
    assert CATEGORY_TO_KIND["information_extraction"] == "extract"
    assert CATEGORY_TO_KIND["summarization"] == "summarise"
    assert CATEGORY_TO_KIND["creative_writing"] == "generate"
    assert CATEGORY_TO_KIND["brainstorming"] == "propose"
    # Three question categories reach one kind, deliberately.
    assert {CATEGORY_TO_KIND[name] for name in ("closed_qa", "open_qa", "general_qa")} == {"answer"}


def test_a_row_becomes_a_public_case_with_an_authored_label():
    cases = cases_from_rows(
        [
            row("closed_qa", context_present=True),
            row("summarization", instruction="summarise this"),
        ]
    )
    assert len(cases) == 2
    assert cases[0].kind == "answer"
    assert cases[0].fields == (PUBLIC_FIELD,)
    assert cases[1].fields == ()
    assert all(case.situations_origin == "public" for case in cases)
    assert all(case.label_origin == "authored" for case in cases)


def test_an_undeclared_category_or_an_empty_instruction_is_refused():
    with pytest.raises(ValueError, match="undeclared category"):
        cases_from_rows([row("new_category")])
    with pytest.raises(ValueError, match="no instruction"):
        cases_from_rows([row("open_qa", instruction="   ")])
    with pytest.raises(TypeError, match="mappings"):
        cases_from_rows(["not a row"])


def test_a_public_corpus_can_never_authorize():
    cases = cases_from_rows(
        [
            row("classification", "classify this sentence"),
            row("summarization", "summarise the paragraph"),
            row("open_qa", "why is the sky blue"),
            row("creative_writing", "write a poem"),
        ]
    )
    report = calibrate_signatures(
        cases,
        schema=public_schema(),
        predictor=VerbFrameSignatureBackend(public_schema()),
        predictor_id="frame.verb-object",
        predictor_version="1",
    )
    assert report.data_origin == "fixture"
    assert report.threshold_authorized is False


def test_mixing_a_public_case_into_captured_outcomes_closes_the_gate():
    cases = tuple(
        SignatureCase(
            f"c{index}",
            "classify this sentence",
            "classify",
            situations_origin="captured",
            label_origin="outcome",
        )
        for index in range(3)
    ) + cases_from_rows([row("open_qa", "why is the sky blue")])
    report = calibrate_signatures(
        cases,
        schema=public_schema(),
        predictor=VerbFrameSignatureBackend(public_schema()),
        predictor_id="frame.verb-object",
        predictor_version="1",
    )
    assert report.data_origin == "fixture"
    assert report.threshold_authorized is False


def test_the_split_keeps_the_memory_disjoint_and_reproducible():
    cases = cases_from_rows(
        [row("open_qa", f"question number {index}") for index in range(10)]
    )
    memory, evaluated = public_split(cases, memory=4)
    assert len(memory) == 4
    assert len(evaluated) == 6
    assert {case.case_id for case in memory} & {case.case_id for case in evaluated} == set()
    assert memory == cases[:4]
    with pytest.raises(ValueError, match="positive integer"):
        public_split(cases, memory=0)
    with pytest.raises(ValueError, match="at least one case"):
        public_split(cases, memory=10)


def test_the_frame_can_reach_every_declared_public_kind_but_the_rule_needs_its_hints():
    schema = public_schema()
    frame = VerbFrameSignatureBackend(schema)
    samples = {
        "summarise this article": "summarise",
        "classify the following sentence": "classify",
        "write a short story": "generate",
        "brainstorm names for a cafe": "propose",
        "explain the water cycle": "answer",
        "extract the dates from the letter": "extract",
    }
    from tiberium_ai.task_signature import predict_signature

    for prompt, expected in samples.items():
        signature = predict_signature(
            schema,
            prompt,
            predictor=frame,
            predictor_id="frame.verb-object",
            predictor_version="1",
        )
        assert signature.kind == expected, prompt
