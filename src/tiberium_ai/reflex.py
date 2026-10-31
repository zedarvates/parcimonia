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

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping, Protocol, Sequence

from .decision_json import STATE_ENCODING_VERSION, canonical_json
from .router import is_nonnegative_number

__all__ = [
    "CalibrationSnapshot",
    "CalibrationBinding",
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
class CalibrationBinding:
    """Identity of one calibrated question, provider and confidence convention."""

    question_name: str
    question_hash: str
    schema_hash: str
    backend_id: str
    backend_version: str
    state_encoding: str = STATE_ENCODING_VERSION
    confidence_metric: str = "provider-confidence/1"

    def __post_init__(self) -> None:
        for name in ("question_name", "backend_id", "backend_version", "state_encoding", "confidence_metric"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a nonempty, trimmed string.")
        for name in ("question_hash", "schema_hash"):
            digest = getattr(self, name)
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)):
                raise ValueError(f"{name} must be a lowercase SHA-256.")


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
    binding: CalibrationBinding | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_family, str) or not self.task_family.strip():
            raise ValueError("task_family must be a nonempty string.")
        if type(self.n_labelled) is not int or self.n_labelled < 0:
            raise ValueError("n_labelled must be a nonnegative integer.")
        if not is_nonnegative_number(self.threshold) or self.threshold > 1.0:
            raise ValueError("threshold must be in [0, 1].")
        if self.data_origin not in ("unmeasured", "fixture", "labelled_outcomes"):
            raise ValueError("data_origin must be unmeasured, fixture or labelled_outcomes.")
        if type(self.measured) is not bool:
            raise TypeError("measured must be a boolean.")
        if type(self.min_labelled) is not int or self.min_labelled < 1:
            raise ValueError("min_labelled must be a positive integer.")
        for name in ("coverage_at_threshold", "accuracy_at_threshold", "min_coverage", "min_accuracy"):
            value = getattr(self, name)
            if value is not None and (not is_nonnegative_number(value) or value > 1):
                raise ValueError(f"{name} must be null or in [0, 1].")
        if self.min_coverage is None or self.min_accuracy is None:
            raise ValueError("minimum coverage and accuracy are required.")
        if self.binding is not None and not isinstance(self.binding, CalibrationBinding):
            raise TypeError("binding must be a CalibrationBinding or null.")

    def matches(self, binding: CalibrationBinding | None) -> bool:
        """A legacy/unbound or unrelated snapshot cannot calibrate this call."""
        return (binding is not None and self.binding == binding
                and self.task_family == f"parcimonia.{binding.question_name}"
                and self.measured and self.data_origin == "labelled_outcomes")

    def permits_auto_act(self, confidence: float | None, *, binding: CalibrationBinding | None = None) -> bool:
        """Statistical eligibility only; execution authority still belongs to the host."""
        if not self.matches(binding) or not is_nonnegative_number(confidence) or confidence > 1:
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
    def __init__(self, backend: ReflexBackend, *, backend_id: str | None = None,
                 backend_version: str | None = None) -> None:
        self.backend = backend
        self._backend_id, self._backend_version = backend_id, backend_version
        for name, declared in (("backend_id", backend_id), ("backend_version", backend_version)):
            actual = getattr(backend, name, None)
            if declared is not None and (not isinstance(declared, str) or not declared.strip()):
                raise ValueError(f"{name} must be a nonempty string or null.")
            if declared is not None and actual is not None and declared != actual:
                raise ValueError(f"declared {name} does not match the backend.")

    def calibration_binding(self, question: ReflexQuestion, *,
                            questions: Sequence[ReflexQuestion] | None = None) -> CalibrationBinding | None:
        backend_id = self._backend_id or getattr(self.backend, "backend_id", None)
        backend_version = self._backend_version or getattr(self.backend, "backend_version", None)
        if not backend_id or not backend_version:
            return None
        schema = tuple(questions) if questions is not None else (question,)
        if question not in schema or len({q.name for q in schema}) != len(schema):
            raise ValueError("calibration question must belong to a unique question schema.")
        record = {**asdict(question), "option_keys": question.option_keys}
        digest = sha256(canonical_json(record).encode("utf-8")).hexdigest()
        schema_record = [{**asdict(q), "option_keys": q.option_keys} for q in schema]
        schema_hash = sha256(canonical_json(schema_record).encode("utf-8")).hexdigest()
        return CalibrationBinding(question.name, digest, schema_hash, backend_id, backend_version)

    def evaluate(
        self,
        state: str | Mapping[str, Any],
        questions: Sequence[ReflexQuestion],
        calibration: CalibrationSnapshot | Mapping[str, CalibrationSnapshot] | None = None,
    ) -> ReflexBatch:
        if not questions:
            raise ValueError("questions cannot be empty.")
        names = [question.name for question in questions]
        if len(set(names)) != len(names):
            raise ValueError("question names must be unique.")
        if calibration is not None and not isinstance(calibration, (CalibrationSnapshot, Mapping)):
            raise TypeError("calibration must be a snapshot, a question mapping or null.")
        if isinstance(calibration, Mapping):
            if set(calibration) - set(names):
                raise ValueError("calibration contains unrequested question names.")
            if any(not isinstance(snapshot, CalibrationSnapshot) for snapshot in calibration.values()):
                raise TypeError("per-question calibration must be a snapshot.")

        if isinstance(state, Mapping):
            state_text = canonical_json(state)
        elif isinstance(state, str):
            state_text = state
        else:
            raise TypeError("state must be a string or mapping.")

        kind = script_kind(state_text)
        latin_only = bool(getattr(self.backend, "latin_only", False))
        refused_script = latin_only and kind == "non_latin"

        raw_answers = self.backend.evaluate(state_text, questions)
        answers: list[ReflexAnswer] = []
        measured = True
        for question in questions:
            snapshot = calibration.get(question.name) if isinstance(calibration, Mapping) else calibration
            binding = self.calibration_binding(question, questions=questions) if snapshot is not None else None
            matched = snapshot is not None and snapshot.matches(binding)
            measured = measured and matched and not refused_script
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
            answers.append(self._materialize(question, raw, snapshot if matched else None, binding))
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
        binding: CalibrationBinding | None = None,
    ) -> ReflexAnswer:
        probs = _validate_probs(question.option_keys, raw)
        confidence = _confidence(raw)
        auto_act = False
        if calibration is not None:
            auto_act = calibration.permits_auto_act(confidence, binding=binding)

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
