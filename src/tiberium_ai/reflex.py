"""Typed reflex decisions over a closed answer space.

Original System-1 contract: a state plus typed questions yields choice, score
or noul values. Types make malformed answers unrepresentable; they do not make
answers true. No Laya/Jev code is vendored, no weights are loaded, and no cloud
API is called.

Fail-closed rules:
* auto-act requires a measured calibration snapshot on this task family
* confidence is None when the backend is uncalibrated
* more than 20 choice options is rejected (two-stage scoring is not implemented)
* a latin-only backend must refuse non-latin state; confidence gating cannot save it
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from .router import is_nonnegative_number

__all__ = [
    "CalibrationSnapshot",
    "InjectedReflexBackend",
    "ReflexAnswer",
    "ReflexBatch",
    "ReflexEngine",
    "ReflexKind",
    "ReflexQuestion",
    "coverage_at_threshold",
    "script_kind",
    "default_reflex_questions",
]

_MAX_CHOICE_OPTIONS = 20


class ReflexKind(str, Enum):
    CHOICE = "choice"
    SCORE = "score"
    NOUL = "noul"


def script_kind(text: str) -> str:
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return "none"
    latin = sum(1 for character in letters if character.isascii())
    if latin / len(letters) < 0.5:
        return "non_latin"
    return "latin"


def coverage_at_threshold(
    confidences: Sequence[float],
    correct: Sequence[bool],
    threshold: float,
) -> tuple[float, float | None]:
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must have the same length.")
    if not confidences:
        raise ValueError("confidences cannot be empty.")
    if not is_nonnegative_number(threshold) or threshold > 1.0:
        raise ValueError("threshold must be a finite number in [0, 1].")
    selected = [ok for conf, ok in zip(confidences, correct) if conf >= threshold]
    coverage = len(selected) / len(confidences)
    if not selected:
        return coverage, None
    accuracy = sum(1 for ok in selected if ok) / len(selected)
    return coverage, accuracy


@dataclass(frozen=True)
class ReflexQuestion:
    name: str
    kind: ReflexKind
    instructions: str
    criteria: Mapping[str, str] | Sequence[str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a nonempty string.")
        if not isinstance(self.kind, ReflexKind):
            raise TypeError("kind must be a ReflexKind enum.")
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("instructions must be a nonempty string.")
        if self.kind == ReflexKind.CHOICE:
            if not isinstance(self.criteria, Mapping) or len(self.criteria) < 2:
                raise ValueError("choice questions require a mapping of at least two options.")
            if any(not isinstance(key, str) or not key.strip() for key in self.criteria):
                raise ValueError("choice option keys must be nonempty strings.")
            if len(self.criteria) > _MAX_CHOICE_OPTIONS:
                raise ValueError(
                    f"choice questions are capped at {_MAX_CHOICE_OPTIONS} options without two-stage scoring."
                )
        elif self.kind == ReflexKind.SCORE:
            if not isinstance(self.criteria, Sequence) or isinstance(self.criteria, (str, bytes)):
                raise ValueError("score questions require an ordered sequence of levels.")
            if len(self.criteria) < 2:
                raise ValueError("score questions require at least two ordered levels.")
        elif self.criteria is not None and not isinstance(self.criteria, Mapping):
            raise ValueError("noul criteria must be a mapping or null.")

    @property
    def option_keys(self) -> tuple[str, ...]:
        if self.kind == ReflexKind.CHOICE and isinstance(self.criteria, Mapping):
            return tuple(self.criteria.keys())
        if self.kind == ReflexKind.SCORE and isinstance(self.criteria, Sequence):
            return tuple(str(level) for level in self.criteria)
        return ("false", "true")


@dataclass(frozen=True)
class CalibrationSnapshot:
    """Measured selective-prediction stats for one task family.

    Unmeasured snapshots cannot authorize auto-act. Accuracy without coverage
    is not a gate: a model that answers 3 of 100 cases at high confidence is
    not calibrated for the remaining 97.
    """

    task_family: str
    measured: bool
    n_labelled: int = 0
    threshold: float = 0.85
    coverage_at_threshold: float | None = None
    accuracy_at_threshold: float | None = None
    brier: float | None = None
    min_labelled: int = 50
    min_coverage: float = 0.3
    min_accuracy: float = 0.9
    data_origin: str = "unmeasured"

    def __post_init__(self) -> None:
        if not isinstance(self.task_family, str) or not self.task_family.strip():
            raise ValueError("task_family must be a nonempty string.")
        if type(self.n_labelled) is not int or self.n_labelled < 0:
            raise ValueError("n_labelled must be a nonnegative integer.")
        if not is_nonnegative_number(self.threshold) or self.threshold > 1.0:
            raise ValueError("threshold must be in [0, 1].")
        if self.data_origin not in ("unmeasured", "fixture", "labelled_outcomes"):
            raise ValueError("data_origin must be unmeasured, fixture or labelled_outcomes.")

    def permits_auto_act(self, confidence: float | None) -> bool:
        if self.data_origin != "labelled_outcomes":
            return False
        if not self.measured or confidence is None:
            return False
        if self.n_labelled < self.min_labelled:
            return False
        if self.coverage_at_threshold is None or self.accuracy_at_threshold is None:
            return False
        if self.coverage_at_threshold < self.min_coverage:
            return False
        if self.accuracy_at_threshold < self.min_accuracy:
            return False
        return confidence >= self.threshold


@dataclass(frozen=True)
class ReflexAnswer:
    name: str
    kind: ReflexKind
    probabilities: Mapping[str, float]
    choice: str | None = None
    score: float | None = None
    noul: float | None = None
    confidence: float | None = None
    auto_act_allowed: bool = False


@dataclass(frozen=True)
class ReflexBatch:
    answers: tuple[ReflexAnswer, ...]
    script: str
    refused_script: bool = False
    uncalibrated: bool = True

    def get(self, name: str) -> ReflexAnswer | None:
        for answer in self.answers:
            if answer.name == name:
                return answer
        return None


class ReflexBackend(Protocol):
    latin_only: bool

    def evaluate(
        self,
        state_text: str,
        questions: Sequence[ReflexQuestion],
    ) -> Mapping[str, Mapping[str, Any]]:
        ...


@dataclass(frozen=True)
class InjectedReflexBackend:
    """Test/shadow backend: answers are supplied, never guessed."""

    answers: Mapping[str, Mapping[str, Any]]
    latin_only: bool = True

    def evaluate(
        self,
        state_text: str,
        questions: Sequence[ReflexQuestion],
    ) -> Mapping[str, Mapping[str, Any]]:
        missing = [question.name for question in questions if question.name not in self.answers]
        if missing:
            raise KeyError(f"Injected backend is missing answers for: {missing}")
        return {question.name: dict(self.answers[question.name]) for question in questions}


def _validate_probs(keys: Sequence[str], raw: Mapping[str, Any]) -> dict[str, float]:
    probs = raw.get("probabilities")
    if not isinstance(probs, Mapping) or not probs:
        raise ValueError("backend answer must include a probabilities mapping.")
    cleaned: dict[str, float] = {}
    total = 0.0
    for key in keys:
        value = probs.get(key)
        if not is_nonnegative_number(value) or value > 1.0:
            raise ValueError(f"probability for {key!r} must be in [0, 1].")
        cleaned[key] = float(value)
        total += float(value)
    extra = set(probs) - set(keys)
    if extra:
        raise ValueError(f"probabilities contain unknown keys: {sorted(extra)}")
    if abs(total - 1.0) > 1e-6:
        raise ValueError("probabilities must sum to 1.")
    return cleaned


def _confidence(raw: Mapping[str, Any]) -> float | None:
    value = raw.get("confidence", None)
    if value is None:
        return None
    if not is_nonnegative_number(value) or value > 1.0:
        raise ValueError("confidence must be null or in [0, 1].")
    return float(value)


class ReflexEngine:
    def __init__(self, backend: ReflexBackend) -> None:
        self.backend = backend

    def evaluate(
        self,
        state: str | Mapping[str, Any],
        questions: Sequence[ReflexQuestion],
        calibration: CalibrationSnapshot | None = None,
    ) -> ReflexBatch:
        if not questions:
            raise ValueError("questions cannot be empty.")
        names = [question.name for question in questions]
        if len(set(names)) != len(names):
            raise ValueError("question names must be unique.")

        if isinstance(state, Mapping):
            state_text = " ".join(str(value) for value in state.values())
        elif isinstance(state, str):
            state_text = state
        else:
            raise TypeError("state must be a string or mapping.")

        kind = script_kind(state_text)
        latin_only = bool(getattr(self.backend, "latin_only", False))
        refused_script = latin_only and kind == "non_latin"

        raw_answers = self.backend.evaluate(state_text, questions)
        measured = calibration.measured if calibration is not None else False
        answers: list[ReflexAnswer] = []
        for question in questions:
            raw = raw_answers.get(question.name)
            if not isinstance(raw, Mapping):
                raise KeyError(f"backend returned no answer for {question.name!r}.")
            if refused_script:
                answers.append(
                    ReflexAnswer(
                        name=question.name,
                        kind=question.kind,
                        probabilities={key: 0.0 for key in question.option_keys},
                        confidence=None,
                        auto_act_allowed=False,
                    )
                )
                continue
            answers.append(self._materialize(question, raw, calibration))
        return ReflexBatch(
            answers=tuple(answers),
            script=kind,
            refused_script=refused_script,
            uncalibrated=not measured,
        )

    def _materialize(
        self,
        question: ReflexQuestion,
        raw: Mapping[str, Any],
        calibration: CalibrationSnapshot | None,
    ) -> ReflexAnswer:
        probs = _validate_probs(question.option_keys, raw)
        confidence = _confidence(raw)
        auto_act = False
        if calibration is not None:
            auto_act = calibration.permits_auto_act(confidence)

        if question.kind == ReflexKind.CHOICE:
            choice = raw.get("choice")
            if choice not in question.option_keys:
                raise ValueError(f"choice {choice!r} is not in the declared option set.")
            return ReflexAnswer(
                name=question.name,
                kind=question.kind,
                probabilities=probs,
                choice=str(choice),
                confidence=confidence,
                auto_act_allowed=auto_act,
            )

        if question.kind == ReflexKind.SCORE:
            score = raw.get("score")
            if not is_nonnegative_number(score):
                raise ValueError("score must be a finite nonnegative number.")
            max_level = float(len(question.option_keys) - 1)
            if score > max_level:
                raise ValueError("score exceeds the declared rubric.")
            return ReflexAnswer(
                name=question.name,
                kind=question.kind,
                probabilities=probs,
                score=float(score),
                confidence=confidence,
                auto_act_allowed=auto_act,
            )

        noul = raw.get("noul")
        if not is_nonnegative_number(noul) or noul > 1.0:
            raise ValueError("noul must be in [0, 1].")
        return ReflexAnswer(
            name=question.name,
            kind=question.kind,
            probabilities=probs,
            noul=float(noul),
            confidence=confidence,
            auto_act_allowed=auto_act,
        )


def default_reflex_questions() -> tuple[ReflexQuestion, ...]:
    return (
        ReflexQuestion(
            name="difficulty",
            kind=ReflexKind.CHOICE,
            instructions="Which compute class does this task need?",
            criteria={
                "deterministic": "local rule, tests, formatting, schema checks",
                "compact": "short local model or structured tool emit",
                "reasoning": "multi-step architecture or open-ended design",
            },
        ),
        ReflexQuestion(
            name="should_continue",
            kind=ReflexKind.NOUL,
            instructions="Should the agent continue this task now?",
        ),
        ReflexQuestion(
            name="needs_browser",
            kind=ReflexKind.NOUL,
            instructions="Does the next step require an authenticated browser session?",
        ),
    )
