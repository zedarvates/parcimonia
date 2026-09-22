"""Task signatures: what an input is about, before any mechanism is chosen.

A route is selected from a Task descriptor: its kind, the capabilities it needs
and the fields worth reading. That descriptor is entirely caller-declared today.
This module adds a predicted descriptor that is advisory, falsifiable and
fail-closed: it can abstain, it never invents a mission, and it authorizes
nothing.

The predictor is a reflex backend and nothing else. A keyword rule, a KNN over
labelled cases and a micro-NN all implement that one protocol, so a learner can
replace the rule without changing this contract, and the rule stays the baseline
that a learner has to beat on the same corpus.

Vocabulary is declared, never invented:

* the schema lists the closed sets: task kinds, capabilities, fields and the goal
  ids the caller already recognises
* a predicted goal is one of those ids or the reserved none option, because a
  predictor that could only name a declared goal would be forced to invent one
* a signature is a proposal with a confidence and a provenance, not a belief
  about the world. Only a measured agreement on labelled outcomes may later let
  anything be trusted from it.

What this module does not do: it predicts no risk class, evidence level or
locality. A prompt is weak evidence for strictness, and the direction of that
error is unsafe, so those dimensions stay caller-declared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from .reflex import ReflexAnswer, ReflexBatch, ReflexEngine, ReflexKind, ReflexQuestion
from .router import is_nonnegative_number
from .verification import hash_input

__all__ = [
    "DeclaredItem",
    "RuleBasedSignatureBackend",
    "SignatureCalibration",
    "SignatureCase",
    "SignatureSchema",
    "TaskSignature",
    "calibrate_signatures",
    "predict_signature",
    "signature_questions",
]

SIGNATURE_SCHEMA_VERSION = 1

#: Reserved goal option meaning "no declared goal applies". Without it a
#: predictor would have to name a goal, which is how a mission gets invented.
NO_GOAL = "none"

#: Stable reason codes.
ABSTAIN_LOW_KIND = "low_kind_confidence"

DATA_ORIGINS = ("unmeasured", "fixture", "labelled_outcomes")

#: Where the inputs came from, and who produced the labels. Both matter: a
#: model-labelled corpus over real situations is the distillation shape, and it
#: still cannot certify itself when the labeller is the predictor. A public
#: corpus is a third origin: it measures a mechanism on vocabulary written by
#: strangers, and it is not this system's work, so it can never authorize.
SITUATIONS_ORIGINS = ("authored", "captured", "public")
LABEL_ORIGINS = ("authored", "model", "outcome")

KIND_QUESTION = "kind"
GOAL_QUESTION = "goal"

MIN_LABELLED_CASES = 20
MIN_COVERAGE = 0.3
MIN_KIND_AGREEMENT = 0.9
MIN_FIELD_PRECISION = 0.9
MIN_FIELD_RECALL = 0.9


def _is_trimmed_nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


@dataclass(frozen=True)
class DeclaredItem:
    """One member of a closed set, with the hints a rule baseline can match."""

    name: str
    hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.name):
            raise ValueError("name must be a nonempty, trimmed string.")
        if isinstance(self.hints, (str, bytes)) or not isinstance(
            self.hints, Sequence
        ):
            raise TypeError("hints must be a sequence of substrings.")
        hints = tuple(self.hints)
        object.__setattr__(self, "hints", hints)
        for hint in hints:
            if not _is_trimmed_nonempty(hint) or hint != hint.lower():
                raise ValueError(
                    "hints must be nonempty, trimmed lowercase substrings, "
                    "because matching happens on lowercased input."
                )


def _check_set(
    items: object, label: str, *, minimum: int = 0, maximum: int | None = None
) -> tuple[DeclaredItem, ...]:
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise TypeError(f"{label} must be a sequence of DeclaredItem.")
    declared = tuple(items)
    if not all(isinstance(item, DeclaredItem) for item in declared):
        raise TypeError(f"{label} must contain DeclaredItem instances.")
    if len(declared) < minimum:
        raise ValueError(f"{label} needs at least {minimum} item(s).")
    if maximum is not None and len(declared) > maximum:
        raise ValueError(
            f"{label} is capped at {maximum} item(s); a wider closed set needs the "
            "staged planning of the decision adapter instead."
        )
    names = [item.name for item in declared]
    if len(set(names)) != len(names):
        raise ValueError(f"{label} must not repeat a name.")
    return declared


@dataclass(frozen=True)
class SignatureSchema:
    """The closed sets one prediction may choose from, and its thresholds.

    Thresholds apply to the probability a rule or a model reports, never to a
    calibrated confidence: nothing here is calibrated until a labelled corpus
    says so.
    """

    name: str
    kinds: tuple[DeclaredItem, ...]
    capabilities: tuple[DeclaredItem, ...] = ()
    fields: tuple[DeclaredItem, ...] = ()
    goals: tuple[DeclaredItem, ...] = ()
    min_kind_confidence: float = 0.9
    min_goal_confidence: float = 0.9
    min_field_confidence: float = 0.5
    min_capability_confidence: float = 0.5

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.name):
            raise ValueError("name must be a nonempty, trimmed string.")
        # The reflex contract accepts at most 20 options in one choice question.
        object.__setattr__(
            self, "kinds", _check_set(self.kinds, "kinds", minimum=2, maximum=20)
        )
        object.__setattr__(
            self, "capabilities", _check_set(self.capabilities, "capabilities")
        )
        object.__setattr__(self, "fields", _check_set(self.fields, "fields"))
        object.__setattr__(
            self, "goals", _check_set(self.goals, "goals", maximum=19)
        )
        if any(item.name == NO_GOAL for item in self.goals):
            raise ValueError(
                f"{NO_GOAL!r} is reserved for the no-goal option and cannot be a "
                "declared goal id."
            )
        for attribute in (
            "min_kind_confidence",
            "min_goal_confidence",
            "min_field_confidence",
            "min_capability_confidence",
        ):
            value = getattr(self, attribute)
            if not is_nonnegative_number(value) or value > 1.0:
                raise ValueError(f"{attribute} must be a finite number in [0, 1].")

    def goal_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.goals) + (NO_GOAL,)

    def field_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    def capability_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.capabilities)

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": SIGNATURE_SCHEMA_VERSION,
            "name": self.name,
            "kinds": [item.name for item in self.kinds],
            "capabilities": [item.name for item in self.capabilities],
            "fields": [item.name for item in self.fields],
            "goals": [item.name for item in self.goals],
            "thresholds": {
                "kind": self.min_kind_confidence,
                "goal": self.min_goal_confidence,
                "field": self.min_field_confidence,
                "capability": self.min_capability_confidence,
            },
        }


def signature_questions(schema: SignatureSchema) -> tuple[ReflexQuestion, ...]:
    """Build the typed questions one signature prediction answers.

    The questions go through the reflex contract unchanged, so an answer batch
    can be captured, recorded, replayed and schema-verified with the decision
    adapter instead of growing a parallel path.
    """
    if not isinstance(schema, SignatureSchema):
        raise TypeError("schema must be a SignatureSchema instance.")
    questions: list[ReflexQuestion] = [
        ReflexQuestion(
            KIND_QUESTION,
            ReflexKind.CHOICE,
            "Which declared task kind does this input belong to?",
            criteria={
                item.name: ", ".join(item.hints) or item.name for item in schema.kinds
            },
        )
    ]
    for item in schema.capabilities:
        questions.append(
            ReflexQuestion(
                f"capability.{item.name}",
                ReflexKind.NOUL,
                f"Does this task require the declared capability {item.name}?",
            )
        )
    for item in schema.fields:
        questions.append(
            ReflexQuestion(
                f"field.{item.name}",
                ReflexKind.NOUL,
                f"Does the input provide the declared field {item.name}?",
            )
        )
    if schema.goals:
        questions.append(
            ReflexQuestion(
                GOAL_QUESTION,
                ReflexKind.CHOICE,
                "Which declared goal does this task serve, or none?",
                criteria={
                    **{
                        item.name: ", ".join(item.hints) or item.name
                        for item in schema.goals
                    },
                    NO_GOAL: "no declared goal applies",
                },
            )
        )
    return tuple(questions)


@dataclass(frozen=True)
class RuleBasedSignatureBackend:
    """Deterministic keyword baseline: no model, no weights, no network.

    A declared item matches when one of its hints appears in the lowercased
    input. Nothing matching a choice question yields a uniform distribution,
    which the threshold then turns into an abstention; several items matching
    split the mass, which abstains too because the input is ambiguous.

    The reported numbers are rule strengths, not calibrated probabilities:
    answers carry confidence None because nothing measured it.
    """

    schema: SignatureSchema
    latin_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.schema, SignatureSchema):
            raise TypeError("schema must be a SignatureSchema instance.")
        if type(self.latin_only) is not bool:
            raise TypeError("latin_only must be a boolean.")

    def evaluate(
        self, state_text: str, questions: Sequence[ReflexQuestion]
    ) -> Mapping[str, Mapping[str, Any]]:
        text = state_text.lower()
        index = {
            **{
                f"capability.{item.name}": item
                for item in self.schema.capabilities
            },
            **{f"field.{item.name}": item for item in self.schema.fields},
        }
        answers: dict[str, Mapping[str, Any]] = {}
        for question in questions:
            if question.name == KIND_QUESTION:
                answers[question.name] = _choice_answer(
                    self.schema.kinds, text, self._matches
                )
            elif question.name == GOAL_QUESTION:
                answers[question.name] = _goal_answer(self.schema.goals, text, self._matches)
            else:
                item = index.get(question.name)
                if item is None:
                    raise KeyError(
                        f"no declared item matches the question {question.name!r}."
                    )
                hit = self._matches(text, item)
                answers[question.name] = {
                    "noul": 1.0 if hit else 0.0,
                    "probabilities": {
                        "false": 0.0 if hit else 1.0,
                        "true": 1.0 if hit else 0.0,
                    },
                    "confidence": None,
                }
        return answers

    def _matches(self, text: str, item: DeclaredItem) -> bool:
        return any(hint in text for hint in item.hints)


def _choice_answer(
    items: Sequence[DeclaredItem], text: str, matches: Any
) -> dict[str, Any]:
    keys = [item.name for item in items]
    matched = [item.name for item in items if matches(text, item)]
    if matched:
        weight = 1.0 / len(matched)
        probabilities = {key: (weight if key in matched else 0.0) for key in keys}
        chosen = matched[0]
    else:
        # Nothing matched: a uniform answer is the honest unknown, and the
        # threshold is what turns it into an abstention.
        weight = 1.0 / len(keys)
        probabilities = {key: weight for key in keys}
        chosen = keys[0]
    return {"choice": chosen, "probabilities": probabilities, "confidence": None}


def _goal_answer(
    goals: Sequence[DeclaredItem], text: str, matches: Any
) -> dict[str, Any]:
    keys = [item.name for item in goals] + [NO_GOAL]
    matched = [item.name for item in goals if matches(text, item)]
    if not matched:
        return {
            "choice": NO_GOAL,
            "probabilities": {key: (1.0 if key == NO_GOAL else 0.0) for key in keys},
            "confidence": None,
        }
    weight = 1.0 / len(matched)
    return {
        "choice": matched[0],
        "probabilities": {key: (weight if key in matched else 0.0) for key in keys},
        "confidence": None,
    }


@dataclass(frozen=True)
class TaskSignature:
    """One predicted task descriptor, with its provenance and its abstention.

    Abstention is a value, not an exception: a signature that could not name a
    kind says so and carries no kind, so a caller cannot read a default kind out
    of a failed prediction.
    """

    schema_name: str
    prompt_hash: str
    kind: str | None
    kind_confidence: float | None
    capabilities: tuple[str, ...]
    capability_scores: Mapping[str, float]
    fields: tuple[str, ...]
    field_scores: Mapping[str, float]
    goal: str | None
    goal_confidence: float | None
    abstained: bool
    reason_code: str | None
    predictor_id: str
    predictor_version: str
    data_origin: str

    def __post_init__(self) -> None:
        for name in ("schema_name", "predictor_id", "predictor_version"):
            if not _is_trimmed_nonempty(getattr(self, name)):
                raise ValueError(f"{name} must be a nonempty, trimmed string.")
        if (
            not isinstance(self.prompt_hash, str)
            or len(self.prompt_hash) != 64
            or any(
                character not in "0123456789abcdef" for character in self.prompt_hash
            )
        ):
            raise ValueError("prompt_hash must be 64 lowercase hexadecimal characters.")
        if self.data_origin not in DATA_ORIGINS:
            raise ValueError(f"data_origin must be one of {list(DATA_ORIGINS)}.")
        if self.abstained and self.kind is not None:
            raise ValueError("an abstained signature cannot name a kind.")
        if not self.abstained and self.kind is None:
            raise ValueError("a determined signature must name a kind.")
        if self.abstained and self.reason_code is None:
            raise ValueError("an abstained signature must carry a reason code.")
        if not self.abstained and self.reason_code is not None:
            raise ValueError("a determined signature carries no reason code.")
        for label, value in (
            ("kind_confidence", self.kind_confidence),
            ("goal_confidence", self.goal_confidence),
        ):
            if value is not None and (
                not is_nonnegative_number(value) or value > 1.0
            ):
                raise ValueError(f"{label} must be null or a finite number in [0, 1].")
        for name in self.capabilities:
            if name not in self.capability_scores:
                raise ValueError(
                    f"capability {name!r} has no score; every selected name is scored."
                )
        for name in self.fields:
            if name not in self.field_scores:
                raise ValueError(
                    f"field {name!r} has no score; every selected name is scored."
                )
        for label, scores in (
            ("capability_scores", self.capability_scores),
            ("field_scores", self.field_scores),
        ):
            for name, value in scores.items():
                if not _is_trimmed_nonempty(name):
                    raise ValueError(f"{label} keys must be nonempty, trimmed names.")
                if not is_nonnegative_number(value) or value > 1.0:
                    raise ValueError(
                        f"{label}[{name!r}] must be a finite number in [0, 1]."
                    )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": SIGNATURE_SCHEMA_VERSION,
            "schema_name": self.schema_name,
            "prompt_hash": self.prompt_hash,
            "kind": self.kind,
            "kind_confidence": self.kind_confidence,
            "capabilities": list(self.capabilities),
            "capability_scores": {
                str(name): value for name, value in self.capability_scores.items()
            },
            "fields": list(self.fields),
            "field_scores": {
                str(name): value for name, value in self.field_scores.items()
            },
            "goal": self.goal,
            "goal_confidence": self.goal_confidence,
            "abstained": self.abstained,
            "reason_code": self.reason_code,
            "auto_act_allowed": False,
            "predictor": {
                "predictor_id": self.predictor_id,
                "predictor_version": self.predictor_version,
            },
            "data_origin": self.data_origin,
        }


def _picked(batch: ReflexBatch, name: str, threshold: float) -> tuple[bool, float | None]:
    answer: ReflexAnswer | None = batch.get(name)
    if answer is None or answer.noul is None:
        return (False, None)
    return (answer.noul >= threshold, answer.noul)


def predict_signature(
    schema: SignatureSchema,
    prompt: str,
    *,
    predictor: Any,
    predictor_id: str,
    predictor_version: str,
    data_origin: str = "fixture",
) -> TaskSignature:
    """Predict a task descriptor, or abstain.

    The provenance is required rather than inferred: a signature nobody can name
    the predictor of is not evidence, and data_origin decides whether a later
    calibration may trust it.
    """
    if not isinstance(schema, SignatureSchema):
        raise TypeError("schema must be a SignatureSchema instance.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a nonempty string.")
    if not callable(getattr(predictor, "evaluate", None)):
        raise TypeError("predictor must provide an evaluate(state, questions) method.")
    for name, value in (
        ("predictor_id", predictor_id),
        ("predictor_version", predictor_version),
    ):
        if not _is_trimmed_nonempty(value):
            raise ValueError(f"{name} must be a nonempty, trimmed string.")
    if data_origin not in DATA_ORIGINS:
        raise ValueError(f"data_origin must be one of {list(DATA_ORIGINS)}.")

    questions = signature_questions(schema)
    batch = ReflexEngine(predictor).evaluate(prompt, questions)

    kind_answer = batch.get(KIND_QUESTION)
    if kind_answer is None or kind_answer.choice is None:
        raise ValueError("the predictor returned no answer for the kind question.")
    kind_confidence = kind_answer.probabilities.get(kind_answer.choice)
    abstained = kind_confidence is None or kind_confidence < schema.min_kind_confidence

    capability_scores: dict[str, float] = {}
    capability_names: list[str] = []
    for item in schema.capabilities:
        selected, score = _picked(
            batch, f"capability.{item.name}", schema.min_capability_confidence
        )
        capability_scores[item.name] = score if score is not None else 0.0
        if selected:
            capability_names.append(item.name)

    field_scores: dict[str, float] = {}
    field_names: list[str] = []
    for item in schema.fields:
        selected, score = _picked(
            batch, f"field.{item.name}", schema.min_field_confidence
        )
        field_scores[item.name] = score if score is not None else 0.0
        if selected:
            field_names.append(item.name)

    goal: str | None = None
    goal_confidence: float | None = None
    if schema.goals:
        goal_answer = batch.get(GOAL_QUESTION)
        if goal_answer is None or goal_answer.choice is None:
            raise ValueError("the predictor returned no answer for the goal question.")
        raw_confidence = goal_answer.probabilities.get(goal_answer.choice)
        if goal_answer.choice == NO_GOAL:
            goal_confidence = raw_confidence
        elif raw_confidence is not None and raw_confidence >= schema.min_goal_confidence:
            goal = goal_answer.choice
            goal_confidence = raw_confidence
        else:
            goal_confidence = raw_confidence

    return TaskSignature(
        schema_name=schema.name,
        prompt_hash=hash_input(prompt),
        kind=None if abstained else kind_answer.choice,
        kind_confidence=kind_confidence,
        capabilities=tuple(capability_names),
        capability_scores=capability_scores,
        fields=tuple(field_names),
        field_scores=field_scores,
        goal=goal,
        goal_confidence=goal_confidence,
        abstained=abstained,
        reason_code=ABSTAIN_LOW_KIND if abstained else None,
        predictor_id=predictor_id,
        predictor_version=predictor_version,
        data_origin=data_origin,
    )


@dataclass(frozen=True)
class SignatureCase:
    """One input with the descriptor it should produce.

    Authored cases say what the rules do; only outcomes of real work say what
    the task needed. The second kind is what a threshold can be built on.
    """

    case_id: str
    prompt: str
    kind: str
    fields: tuple[str, ...] = ()
    goal: str | None = None
    situations_origin: str = "authored"
    label_origin: str = "authored"

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.case_id):
            raise ValueError("case_id must be a nonempty, trimmed string.")
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be a nonempty string.")
        if not _is_trimmed_nonempty(self.kind):
            raise ValueError("kind must be a nonempty, trimmed string.")
        if isinstance(self.fields, (str, bytes)) or not isinstance(
            self.fields, Sequence
        ):
            raise TypeError("fields must be a sequence of field names.")
        fields = tuple(self.fields)
        object.__setattr__(self, "fields", fields)
        for name in fields:
            if not _is_trimmed_nonempty(name):
                raise ValueError("field names must be nonempty, trimmed strings.")
        if len(set(fields)) != len(fields):
            raise ValueError("fields must not repeat a name.")
        if self.goal is not None and not _is_trimmed_nonempty(self.goal):
            raise ValueError("goal must be null or a nonempty, trimmed string.")
        if self.situations_origin not in SITUATIONS_ORIGINS:
            raise ValueError(
                f"situations_origin must be one of {list(SITUATIONS_ORIGINS)}."
            )
        if self.label_origin not in LABEL_ORIGINS:
            raise ValueError(f"label_origin must be one of {list(LABEL_ORIGINS)}.")


@dataclass(frozen=True)
class SignatureCalibration:
    """What one corpus says about one predictor, and what it may authorize.

    A snapshot cannot be constructed as authorized unless it came from labelled
    outcomes, so a fixture run cannot be promoted by editing a field.
    """

    schema_name: str
    predictor_id: str
    predictor_version: str
    data_origin: str
    cases: int
    abstained: int
    coverage: float
    kind_agreement: float | None
    field_precision: float | None
    field_recall: float | None
    goal_agreement: float | None
    threshold_authorized: bool
    observations: tuple[Mapping[str, Any], ...] = ()
    min_cases: int = MIN_LABELLED_CASES
    #: Who produced the labels, when something other than a human did. A report
    #: whose labeller is its own predictor is self-confirming and cannot
    #: authorize, whatever its numbers.
    labeler_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("schema_name", "predictor_id", "predictor_version"):
            if not _is_trimmed_nonempty(getattr(self, name)):
                raise ValueError(f"{name} must be a nonempty, trimmed string.")
        if self.data_origin not in DATA_ORIGINS:
            raise ValueError(f"data_origin must be one of {list(DATA_ORIGINS)}.")
        if self.threshold_authorized and self.data_origin != "labelled_outcomes":
            raise ValueError(
                "only labelled outcomes can authorize a threshold; a fixture "
                "snapshot says what the rules do, not what the task needed."
            )
        if self.threshold_authorized and not self.independent:
            raise ValueError(
                "a predictor cannot authorize a threshold on labels it produced "
                "itself; agreement with its own labels is not agreement with the "
                "task."
            )
        if type(self.cases) is not int or self.cases < 1:
            raise ValueError("cases must be a positive integer.")
        if type(self.abstained) is not int or not 0 <= self.abstained <= self.cases:
            raise ValueError("abstained must be an integer between 0 and cases.")
        for label, value in (
            ("coverage", self.coverage),
            ("kind_agreement", self.kind_agreement),
            ("field_precision", self.field_precision),
            ("field_recall", self.field_recall),
            ("goal_agreement", self.goal_agreement),
        ):
            if value is not None and (
                not is_nonnegative_number(value) or value > 1.0
            ):
                raise ValueError(f"{label} must be null or a finite number in [0, 1].")

    @property
    def determinate(self) -> bool:
        """Return whether coverage and kind agreement were both observed."""
        return self.kind_agreement is not None and self.coverage > 0

    @property
    def independent(self) -> bool:
        """Return whether the labels came from something other than the predictor."""
        return self.labeler_id is None or self.labeler_id != self.predictor_id

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": SIGNATURE_SCHEMA_VERSION,
            "schema_name": self.schema_name,
            "predictor": {
                "predictor_id": self.predictor_id,
                "predictor_version": self.predictor_version,
            },
            "data_origin": self.data_origin,
            "cases": self.cases,
            "abstained": self.abstained,
            "coverage": self.coverage,
            "kind_agreement": self.kind_agreement,
            "field_precision": self.field_precision,
            "field_recall": self.field_recall,
            "goal_agreement": self.goal_agreement,
            "threshold_authorized": self.threshold_authorized,
            "labeler_id": self.labeler_id,
            "independent": self.independent,
            "min_cases": self.min_cases,
            "observations": [dict(entry) for entry in self.observations],
            "claim": (
                "agreement measured on the declared corpus; only labelled "
                "outcomes can authorize a threshold"
            ),
        }


def _check_case(case: SignatureCase, schema: SignatureSchema) -> None:
    if case.kind not in {item.name for item in schema.kinds}:
        raise ValueError(f"case {case.case_id!r} names an undeclared kind.")
    declared_fields = set(schema.field_names())
    undeclared = sorted(name for name in case.fields if name not in declared_fields)
    if undeclared:
        raise ValueError(
            f"case {case.case_id!r} names undeclared field(s) {undeclared}."
        )
    if case.goal is not None and case.goal not in {
        item.name for item in schema.goals
    }:
        raise ValueError(f"case {case.case_id!r} names an undeclared goal.")


def calibrate_signatures(
    cases: Sequence[SignatureCase],
    *,
    schema: SignatureSchema,
    predictor: Any,
    predictor_id: str,
    predictor_version: str,
    labeler_id: str | None = None,
) -> SignatureCalibration:
    """Measure one predictor against one corpus, and refuse to promote it.

    Agreement is reported on the cases the predictor was willing to answer, and
    coverage says how many those were: an accurate predictor that answers three
    cases out of a hundred is not calibrated for the other ninety-seven.
    """
    if not isinstance(schema, SignatureSchema):
        raise TypeError("schema must be a SignatureSchema instance.")
    declared = tuple(cases)
    if not declared:
        raise ValueError("at least one case is required.")
    identifiers = [case.case_id for case in declared]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate case ids are not allowed.")
    for case in declared:
        if not isinstance(case, SignatureCase):
            raise TypeError("cases must contain SignatureCase instances.")
        _check_case(case, schema)
    if labeler_id is not None and not _is_trimmed_nonempty(labeler_id):
        raise ValueError("labeler_id must be null or a nonempty, trimmed string.")

    # The provenance is read from the cases rather than passed in, so no caller
    # can promote an authored corpus by editing one argument.
    data_origin = (
        "labelled_outcomes"
        if all(case.situations_origin == "captured" for case in declared)
        and all(case.label_origin == "outcome" for case in declared)
        else "fixture"
    )
    independent = labeler_id is None or labeler_id != predictor_id

    pairs = [
        (
            case,
            predict_signature(
                schema,
                case.prompt,
                predictor=predictor,
                predictor_id=predictor_id,
                predictor_version=predictor_version,
                data_origin=data_origin,
            ),
        )
        for case in declared
    ]
    covered = [(case, signature) for case, signature in pairs if not signature.abstained]
    coverage = len(covered) / len(pairs)
    kind_agreement = (
        sum(1 for case, signature in covered if signature.kind == case.kind)
        / len(covered)
        if covered
        else None
    )
    true_positives = sum(
        len(set(signature.fields) & set(case.fields)) for case, signature in covered
    )
    predicted_total = sum(len(signature.fields) for _, signature in covered)
    expected_total = sum(len(case.fields) for case, _ in covered)
    goal_cases = [(case, signature) for case, signature in covered if case.goal]
    goal_agreement = (
        sum(1 for case, signature in goal_cases if signature.goal == case.goal)
        / len(goal_cases)
        if goal_cases
        else None
    )
    field_precision = (true_positives / predicted_total) if predicted_total else None
    field_recall = (true_positives / expected_total) if expected_total else None
    authorized = (
        data_origin == "labelled_outcomes"
        and independent
        and len(pairs) >= MIN_LABELLED_CASES
        and coverage >= MIN_COVERAGE
        and kind_agreement is not None
        and kind_agreement >= MIN_KIND_AGREEMENT
        and field_precision is not None
        and field_precision >= MIN_FIELD_PRECISION
        and field_recall is not None
        and field_recall >= MIN_FIELD_RECALL
    )

    observations = tuple(
        {
            "case_id": case.case_id,
            "prompt_hash": signature.prompt_hash,
            "abstained": signature.abstained,
            "kind": signature.kind,
            "expected_kind": case.kind,
            "fields": list(signature.fields),
            "expected_fields": list(case.fields),
            "goal": signature.goal,
            "expected_goal": case.goal,
        }
        for case, signature in pairs
    )
    return SignatureCalibration(
        schema_name=schema.name,
        predictor_id=predictor_id,
        predictor_version=predictor_version,
        data_origin=data_origin,
        cases=len(pairs),
        abstained=len(pairs) - len(covered),
        coverage=coverage,
        kind_agreement=kind_agreement,
        field_precision=field_precision,
        field_recall=field_recall,
        goal_agreement=goal_agreement,
        threshold_authorized=authorized,
        labeler_id=labeler_id,
        observations=observations,
    )
