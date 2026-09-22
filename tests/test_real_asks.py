import pytest

from tiberium_ai.real_asks import (
    LABELS_ABSENT,
    agreement_triage,
    measure_coverage,
    reachable_schema,
)
from tiberium_ai.signature_backends import (
    VerbFrameSignatureBackend,
)
from tiberium_ai.task_signature import RuleBasedSignatureBackend, predict_signature


class FixedBackend:
    """Answers the kind question from a table, or abstains by being uniform."""

    latin_only = False

    def __init__(self, mapping, default=None):
        self.mapping = mapping
        self.default = default

    def evaluate(self, state_text, questions):
        answers = {}
        for question in questions:
            keys = list(question.option_keys)
            if question.kind.value != "choice":
                answers[question.name] = {
                    "noul": 0.0,
                    "probabilities": {"false": 1.0, "true": 0.0},
                    "confidence": None,
                }
                continue
            winner = self.mapping.get(state_text, self.default)
            if winner is None:
                weight = 1.0 / len(keys)
                answers[question.name] = {
                    "choice": keys[0],
                    "probabilities": {key: weight for key in keys},
                    "confidence": None,
                }
            else:
                answers[question.name] = {
                    "choice": winner,
                    "probabilities": {key: (1.0 if key == winner else 0.0) for key in keys},
                    "confidence": None,
                }
        return answers


def entry(text, count=1, case_id="p1"):
    return {"text": text, "count": count, "id": case_id}


def test_every_action_the_lexicon_expresses_becomes_a_declared_kind():
    schema = reachable_schema()
    names = [item.name for item in schema.kinds]
    assert len(names) >= 2
    assert names == sorted(names)
    assert all(item.hints for item in schema.kinds)
    frame = VerbFrameSignatureBackend(schema)
    for prompt, expected in (
        ("extract the columns", "extract"),
        ("summarise the report", "summarise"),
        ("classify these sentences", "classify"),
    ):
        signature = predict_signature(
            schema,
            prompt,
            predictor=frame,
            predictor_id="frame",
            predictor_version="1",
        )
        assert signature.kind == expected, prompt


def test_coverage_counts_what_is_answered_and_where_it_abstains():
    schema = reachable_schema()
    prompts = (
        entry("extract the columns", 3, "a"),
        entry("continuer", 5, "b"),
        entry("zzz", 1, "c"),
    )
    reports = measure_coverage(
        prompts,
        predictors={"rule.keyword": RuleBasedSignatureBackend(schema)},
        schema=schema,
    )
    report = reports[0]
    assert report.distinct == 3
    assert report.volume == 9
    assert report.answered_distinct == 1
    assert report.answered_volume == 3
    assert report.coverage_volume == pytest.approx(1 / 3)
    assert report.coverage_distinct == pytest.approx(1 / 3)
    assert report.actions == {"extract": 3}
    # Every sample here is short, so one band carries the whole corpus.
    assert report.by_band["short<30"] == {"total": 9, "answered": 3}


def test_agreement_separates_unanimous_from_split_and_from_unanswered():
    schema = reachable_schema()
    prompts = (
        entry("same answer here", 4, "a"),
        entry("two different answers", 2, "b"),
        entry("nobody answers this", 1, "c"),
    )
    first = FixedBackend(
        {"same answer here": "extract", "two different answers": "extract"},
        default=None,
    )
    second = FixedBackend(
        {"same answer here": "extract", "two different answers": "verify"},
        default=None,
    )
    third = FixedBackend({}, default=None)
    triage = agreement_triage(
        prompts,
        predictors={"a": first, "b": second, "c": third},
        schema=schema,
    )
    assert triage["buckets"]["unanimous"] == {"distinct": 1, "volume": 4}
    assert triage["buckets"]["split"] == {"distinct": 1, "volume": 2}
    assert triage["buckets"]["insufficient"] == {"distinct": 1, "volume": 1}
    assert triage["buckets"]["majority"] == {"distinct": 0, "volume": 0}
    # Shares are reported rounded to four decimals.
    assert triage["unanimous_share"] == pytest.approx(4 / 7, abs=1e-4)
    assert triage["needs_a_label_share"] == pytest.approx(2 / 7, abs=1e-4)
    assert triage["example_ids"]["split"] == ["b"]
    assert triage["reading"] == LABELS_ABSENT


def test_a_two_against_one_vote_is_a_majority_not_a_split():
    schema = reachable_schema()
    prompts = (entry("contested", 1, "a"),)
    predictors = {
        "a": FixedBackend({"contested": "extract"}),
        "b": FixedBackend({"contested": "extract"}),
        "c": FixedBackend({"contested": "verify"}),
    }
    triage = agreement_triage(prompts, predictors=predictors, schema=schema)
    assert triage["buckets"]["majority"] == {"distinct": 1, "volume": 1}
    assert triage["buckets"]["split"]["distinct"] == 0


def test_the_lane_validates_what_it_cannot_measure():
    with pytest.raises(ValueError, match="at least one prompt"):
        measure_coverage((), predictors={"a": FixedBackend({})})
    with pytest.raises(ValueError, match="at least one predictor"):
        measure_coverage((entry("x"),), predictors={})
    with pytest.raises(ValueError, match="at least two predictors"):
        agreement_triage((entry("x"),), predictors={"a": FixedBackend({})})
    with pytest.raises(ValueError, match="at least one prompt"):
        agreement_triage((), predictors={"a": FixedBackend({}), "b": FixedBackend({})})
