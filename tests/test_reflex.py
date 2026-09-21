import pytest

from tiberium_ai.reflex import (
    CalibrationSnapshot,
    InjectedReflexBackend,
    ReflexEngine,
    ReflexKind,
    ReflexQuestion,
    coverage_at_threshold,
    script_kind,
)


CHOICE_Q = ReflexQuestion(
    name="difficulty",
    kind=ReflexKind.CHOICE,
    instructions="Which compute class?",
    criteria={"deterministic": "rules", "compact": "small", "reasoning": "hard"},
)
NOUL_Q = ReflexQuestion(
    name="should_continue",
    kind=ReflexKind.NOUL,
    instructions="Continue now?",
)
SCORE_Q = ReflexQuestion(
    name="urgency",
    kind=ReflexKind.SCORE,
    instructions="How urgent?",
    criteria=("low", "medium", "high"),
)


def test_choice_cardinality_cap():
    criteria = {f"opt{i}": "x" for i in range(21)}
    with pytest.raises(ValueError, match="capped at 20"):
        ReflexQuestion("too_big", ReflexKind.CHOICE, "pick", criteria=criteria)


def test_types_do_not_certify_truth():
    backend = InjectedReflexBackend(
        answers={
            "difficulty": {
                "choice": "reasoning",
                "probabilities": {"deterministic": 0.05, "compact": 0.05, "reasoning": 0.9},
                "confidence": 0.9,
            }
        }
    )
    engine = ReflexEngine(backend)
    batch = engine.evaluate("run the linter", [CHOICE_Q])
    answer = batch.get("difficulty")
    assert answer is not None
    assert answer.choice == "reasoning"
    assert answer.auto_act_allowed is False


def test_uncalibrated_cannot_auto_act():
    backend = InjectedReflexBackend(
        answers={
            "should_continue": {
                "noul": 0.99,
                "probabilities": {"false": 0.01, "true": 0.99},
                "confidence": 0.99,
            }
        }
    )
    snapshot = CalibrationSnapshot(task_family="parcimonia-continue", measured=False)
    batch = ReflexEngine(backend).evaluate("continue", [NOUL_Q], calibration=snapshot)
    assert batch.uncalibrated is True
    assert batch.get("should_continue").auto_act_allowed is False


def test_measured_calibration_permits_auto_act():
    backend = InjectedReflexBackend(
        answers={
            "should_continue": {
                "noul": 0.96,
                "probabilities": {"false": 0.04, "true": 0.96},
                "confidence": 0.96,
            }
        }
    )
    snapshot = CalibrationSnapshot(
        task_family="parcimonia-continue",
        measured=True,
        n_labelled=80,
        threshold=0.85,
        coverage_at_threshold=0.5,
        accuracy_at_threshold=0.94,
        brier=0.08,
        data_origin="labelled_outcomes",
    )
    batch = ReflexEngine(backend).evaluate("continue", [NOUL_Q], calibration=snapshot)
    assert batch.uncalibrated is False
    assert batch.get("should_continue").auto_act_allowed is True


def test_latin_only_backend_refuses_khmer():
    backend = InjectedReflexBackend(
        answers={
            "difficulty": {
                "choice": "compact",
                "probabilities": {"deterministic": 0.1, "compact": 0.8, "reasoning": 0.1},
                "confidence": 0.95,
            }
        },
        latin_only=True,
    )
    khmer = "សួស្តី នេះជាកិច្ចការ"
    batch = ReflexEngine(backend).evaluate(khmer, [CHOICE_Q])
    assert script_kind(khmer) == "non_latin"
    assert batch.refused_script is True
    assert batch.get("difficulty").confidence is None
    assert batch.get("difficulty").auto_act_allowed is False


def test_score_and_noul_shapes():
    backend = InjectedReflexBackend(
        answers={
            "urgency": {
                "score": 2.0,
                "probabilities": {"low": 0.05, "medium": 0.1, "high": 0.85},
                "confidence": None,
            },
            "should_continue": {
                "noul": 0.5,
                "probabilities": {"false": 0.5, "true": 0.5},
                "confidence": None,
            },
        }
    )
    batch = ReflexEngine(backend).evaluate("maybe later", [SCORE_Q, NOUL_Q])
    assert batch.get("urgency").score == 2.0
    assert batch.get("should_continue").noul == 0.5
    assert batch.get("should_continue").auto_act_allowed is False


def test_coverage_at_threshold_is_not_accuracy():
    confidences = [0.95, 0.94, 0.4, 0.3]
    correct = [True, True, False, True]
    coverage, accuracy = coverage_at_threshold(confidences, correct, 0.9)
    assert coverage == 0.5
    assert accuracy == 1.0


def test_injected_backend_does_not_guess():
    engine = ReflexEngine(InjectedReflexBackend(answers={}))
    with pytest.raises(KeyError, match="missing answers"):
        engine.evaluate("hello", [CHOICE_Q])
