"""Fixture calibration harness for typed reflex questions.

Runs a local hint backend against labelled cases and records coverage,
accuracy and Brier score. Fixture origin cannot authorize auto-act.
No neural weights are loaded and no cloud API is called.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .reflex import (
    CalibrationSnapshot,
    ReflexEngine,
    ReflexKind,
    ReflexQuestion,
    coverage_at_threshold,
    default_reflex_questions,
)
from .router import is_nonnegative_number

__all__ = [
    "CalibrationReport",
    "HintReflexBackend",
    "LabelledCase",
    "brier_choice",
    "brier_noul",
    "calibrate_parcimonia_fixtures",
    "evaluate_calibration",
]


@dataclass(frozen=True)
class LabelledCase:
    case_id: str
    state: str
    labels: Mapping[str, str | float | bool]

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("case_id must be a nonempty string.")
        if not isinstance(self.state, str) or not self.state.strip():
            raise ValueError("state must be a nonempty string.")
        if not self.labels:
            raise ValueError("labels cannot be empty.")


@dataclass(frozen=True)
class CalibrationReport:
    snapshots: tuple[CalibrationSnapshot, ...]
    n_cases: int
    data_origin: str
    backend: str

    def for_question(self, task_family: str) -> CalibrationSnapshot | None:
        for snapshot in self.snapshots:
            if snapshot.task_family == task_family:
                return snapshot
        return None

    def authorizes_auto_act(self) -> bool:
        return any(
            snapshot.permits_auto_act(snapshot.threshold) for snapshot in self.snapshots
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "reflex_calibration",
            "data_origin": self.data_origin,
            "backend": self.backend,
            "n_cases": self.n_cases,
            "authorizes_auto_act": self.authorizes_auto_act(),
            "snapshots": [
                {
                    "task_family": snapshot.task_family,
                    "measured": snapshot.measured,
                    "data_origin": snapshot.data_origin,
                    "n_labelled": snapshot.n_labelled,
                    "threshold": snapshot.threshold,
                    "coverage_at_threshold": snapshot.coverage_at_threshold,
                    "accuracy_at_threshold": snapshot.accuracy_at_threshold,
                    "brier": snapshot.brier,
                }
                for snapshot in self.snapshots
            ],
        }


_DETERMINISTIC_HINTS = (
    "pytest",
    "lint",
    "typecheck",
    "format",
    "schema",
    "exact match",
    "exact-match",
    "runner result",
    "parse json",
    "hash",
    "sort",
    "deterministic",
    "shape of",
    "iso-8601",
    "count failed",
)
_COMPACT_HINTS = (
    "adapter",
    "docstring",
    "rename",
    "mirror",
    "markdown",
    "envelope",
    "time budget",
    "syntax",
    "compact",
    "alias",
    "serialize",
    "trim whitespace",
    "map routekind",
    "webbrain mcp",
    "max_step_tokens",
)
_REASONING_HINTS = (
    "architecture",
    "world model",
    "director policy",
    "multi-agent",
    "routing strategy",
    "calibration theory",
    "subsystem",
    "supervisor design",
    "cost/risk",
    "reason about",
    "predictor",
    "open questions",
)
_CONTINUE_NO = (
    "freeze",
    "stall",
    "quota critical",
    "high risk",
    "critical risk",
    "no time",
    "require human",
    "kill switch",
    "overrode",
    "silence is not approval",
    "waiting for human",
    "do not continue",
    "production data",
)
_CONTINUE_YES = (
    "run pytest",
    "eligible",
    "verified",
    "nominal",
    "write a compact",
    "add a docstring",
)
_BROWSER_YES = (
    "webbrain",
    "browser",
    "pricing table",
    "pricing page",
    "authenticated",
    "form",
    "click through",
    "login form",
)
_BROWSER_NO = (
    "pytest",
    "typecheck",
    "markdown",
    "kanban",
    "local",
    "unit test",
    "no network",
)


def _hits(text: str, hints: Sequence[str]) -> int:
    folded = text.casefold()
    return sum(1 for hint in hints if hint in folded)


def _normalize(scores: Mapping[str, float]) -> dict[str, float]:
    total = sum(scores.values())
    if total <= 0:
        share = 1.0 / len(scores)
        return {key: share for key in scores}
    return {key: value / total for key, value in scores.items()}


def _margin_confidence(probs: Mapping[str, float]) -> float:
    ordered = sorted(probs.values(), reverse=True)
    top = ordered[0]
    second = ordered[1] if len(ordered) > 1 else 0.0
    return max(0.0, min(1.0, top - second + (top - 1.0 / max(len(probs), 1))))


class HintReflexBackend:
    """Deterministic keyword hinter. Peakedness is not a calibrated head."""

    latin_only = True

    def evaluate(
        self,
        state_text: str,
        questions: Sequence[ReflexQuestion],
    ) -> Mapping[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        for question in questions:
            if question.kind == ReflexKind.CHOICE and question.name == "difficulty":
                out[question.name] = self._difficulty(state_text, question)
            elif question.kind == ReflexKind.NOUL and question.name == "should_continue":
                out[question.name] = self._noul(state_text, _CONTINUE_YES, _CONTINUE_NO)
            elif question.kind == ReflexKind.NOUL and question.name == "needs_browser":
                out[question.name] = self._noul(state_text, _BROWSER_YES, _BROWSER_NO)
            else:
                raise KeyError(f"HintReflexBackend has no rule for {question.name!r}.")
        return out

    def _difficulty(self, state_text: str, question: ReflexQuestion) -> dict[str, Any]:
        scores = {
            "deterministic": 1.0 + 4.0 * _hits(state_text, _DETERMINISTIC_HINTS),
            "compact": 1.0 + 4.0 * _hits(state_text, _COMPACT_HINTS),
            "reasoning": 1.0 + 4.0 * _hits(state_text, _REASONING_HINTS),
        }
        probs = _normalize(scores)
        choice = max(probs, key=probs.get)
        return {
            "choice": choice,
            "probabilities": probs,
            "confidence": _margin_confidence(probs),
        }

    def _noul(
        self,
        state_text: str,
        yes_hints: Sequence[str],
        no_hints: Sequence[str],
    ) -> dict[str, Any]:
        yes = 1.0 + 4.0 * _hits(state_text, yes_hints)
        no = 1.0 + 4.0 * _hits(state_text, no_hints)
        noul = yes / (yes + no)
        return {
            "noul": noul,
            "probabilities": {"false": 1.0 - noul, "true": noul},
            "confidence": abs(noul - 0.5) * 2.0,
        }


def brier_choice(probabilities: Mapping[str, float], label: str) -> float:
    if label not in probabilities:
        raise ValueError(f"label {label!r} is not in the probability keys.")
    return sum((value - (1.0 if key == label else 0.0)) ** 2 for key, value in probabilities.items())


def brier_noul(probability: float, label: bool) -> float:
    if not is_nonnegative_number(probability) or probability > 1.0:
        raise ValueError("probability must be in [0, 1].")
    outcome = 1.0 if label else 0.0
    return (probability - outcome) ** 2


def evaluate_calibration(
    engine: ReflexEngine,
    questions: Sequence[ReflexQuestion],
    cases: Sequence[LabelledCase],
    *,
    threshold: float = 0.85,
    data_origin: str = "fixture",
    min_labelled: int = 50,
) -> CalibrationReport:
    if data_origin not in ("fixture", "labelled_outcomes"):
        raise ValueError("data_origin must be fixture or labelled_outcomes.")
    if not cases:
        raise ValueError("cases cannot be empty.")
    by_name = {question.name: question for question in questions}
    per_question: dict[str, dict[str, list[Any]]] = {
        question.name: {"conf": [], "ok": [], "brier": []} for question in questions
    }

    for case in cases:
        asked = [by_name[name] for name in case.labels if name in by_name]
        if not asked:
            continue
        batch = engine.evaluate(case.state, asked)
        for name, label in case.labels.items():
            question = by_name.get(name)
            if question is None:
                continue
            answer = batch.get(name)
            if answer is None:
                raise KeyError(f"engine returned no answer for {name!r} on {case.case_id}.")
            if question.kind == ReflexKind.CHOICE:
                correct = answer.choice == label
                brier = brier_choice(answer.probabilities, str(label))
                confidence = answer.confidence if answer.confidence is not None else 0.0
            elif question.kind == ReflexKind.NOUL:
                if type(label) is not bool:
                    raise TypeError(f"noul label for {name!r} must be a boolean.")
                predicted = answer.noul is not None and answer.noul >= 0.5
                correct = predicted == label
                brier = brier_noul(answer.noul if answer.noul is not None else 0.5, label)
                if answer.noul is None:
                    confidence = 0.0
                else:
                    confidence = abs(answer.noul - 0.5) * 2.0
            else:
                raise ValueError(f"unsupported question kind for calibration: {question.kind}.")
            bucket = per_question[name]
            bucket["conf"].append(float(confidence))
            bucket["ok"].append(bool(correct))
            bucket["brier"].append(float(brier))

    snapshots: list[CalibrationSnapshot] = []
    measured = data_origin == "labelled_outcomes"
    for question in questions:
        bucket = per_question[question.name]
        n_labelled = len(bucket["ok"])
        if n_labelled == 0:
            continue
        coverage, accuracy = coverage_at_threshold(bucket["conf"], bucket["ok"], threshold)
        brier = sum(bucket["brier"]) / n_labelled
        snapshots.append(
            CalibrationSnapshot(
                task_family=f"parcimonia.{question.name}",
                measured=measured,
                n_labelled=n_labelled,
                threshold=threshold,
                coverage_at_threshold=coverage,
                accuracy_at_threshold=accuracy,
                brier=brier,
                min_labelled=min_labelled,
                data_origin=data_origin,
            )
        )
    return CalibrationReport(
        snapshots=tuple(snapshots),
        n_cases=len(cases),
        data_origin=data_origin,
        backend=type(engine.backend).__name__,
    )


def calibrate_parcimonia_fixtures(
    *,
    threshold: float = 0.85,
) -> CalibrationReport:
    from .reflex_corpus import parcimonia_reflex_cases

    engine = ReflexEngine(HintReflexBackend())
    return evaluate_calibration(
        engine,
        default_reflex_questions(),
        parcimonia_reflex_cases(),
        threshold=threshold,
        data_origin="fixture",
    )

