"""Typed-decision routes: how one is asked, decomposed, replayed and verified.

Parcimonia's reflex contract already fixes the shape of a decision: a state
plus typed questions yields choice, score or noul values with probabilities.
A route built on a decision model still needs three pieces before a real call
is worth making, and this module supplies them without making that call:

* an option set whose cardinality may exceed one call's option cap, split into
  balanced stages that respect the cap and recomposed deterministically
* a request envelope, a recorded response and the provenance that replays it,
  so one authorized call becomes evidence instead of a demonstration
* a route manifest entry and a deterministic verifier that recomputes the
  composed decision rather than trusting the caller's claim

No decision-model code is vendored, no weights are loaded and no network call
is made: the transport is injected, as in the WebBrain adapter, and its absence
is a typed unavailable capture rather than an exception.

Non-goals, stated because they bound what a result here can mean: no training,
no calibration, and no claim that a decomposed decision equals one wide call.
The composition chooses within each declared group and then among the winning
groups, so a group's winner can still be wrong; per-option independent scoring
is left unimplemented on purpose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .decision_clock import (
    DecisionBudget,
    DecisionTiming,
    TimingVerdict,
    assess_decision_timing,
)
from .reflex import (
    InjectedReflexBackend,
    ReflexBatch,
    ReflexEngine,
    ReflexKind,
    ReflexQuestion,
)
from .router import is_nonnegative_number
from .verification import VerifierRegistry, hash_input

__all__ = [
    "DECISION_CAPABILITY",
    "DECISION_VERIFIER_ID",
    "DECISION_VERIFIER_VERSION",
    "MAX_CHOICE_OPTIONS",
    "SCHEMA_VERIFIER_ID",
    "SCHEMA_VERIFIER_VERSION",
    "SCORED_VERIFIER_ID",
    "SCORED_VERIFIER_VERSION",
    "SINGLE_STAGE_CHOICE_CAP",
    "DecisionCapture",
    "DecisionRecord",
    "DecisionReplay",
    "DecisionRequest",
    "OptionSetQuestion",
    "ScoredDecision",
    "ScoredPlan",
    "TwoStageDecision",
    "TwoStagePlan",
    "capture_decision",
    "compose_two_stage",
    "compose_scored",
    "decision_route_entry",
    "plan_scored_stages",
    "plan_two_stage",
    "read_decision_record",
    "register_decision_verifiers",
    "replay_decision",
    "schema_payload",
    "schema_verifier",
    "scored_payload",
    "scored_verifier",
    "scored_stage_questions",
    "stage_questions",
    "two_stage_payload",
    "two_stage_verifier",
    "write_decision_record",
]

#: Options one call may offer, matching the reflex contract's cap.
SINGLE_STAGE_CHOICE_CAP = 20

#: Ceiling of the decision-model class this contract targets. Above it a
#: decision is refused instead of approximated by a third stage.
MAX_CHOICE_OPTIONS = 255

#: Capability this route provides. A consumer asks for a typed decision; it
#: never asks for "the Jev route".
DECISION_CAPABILITY = "decision.typed@1"

DECISION_VERIFIER_ID = "decision.two_stage"
DECISION_VERIFIER_VERSION = "1"

SCORED_VERIFIER_ID = "decision.scored"
SCORED_VERIFIER_VERSION = "1"

#: Schema conformance of one recorded response against the request it answers.
#: It says the answer is well formed, never that it is right.
SCHEMA_VERIFIER_ID = "decision.schema"
SCHEMA_VERIFIER_VERSION = "1"

REQUEST_SCHEMA_VERSION = 1
RECORD_SCHEMA_VERSION = 1

DECISION_RECORD_KIND = "decision_record"

DECIDED_SINGLE_STAGE = "single_stage_choice"
DECIDED_TWO_STAGE = "two_stage_composed"
UNDETERMINED_INCOMPLETE = "incomplete_stage"

DATA_ORIGINS = ("recorded", "fixture")
_USAGE_FIELDS = (
    "input_tokens_total",
    "output_tokens_total",
    "n_retries",
    "latency_ms",
)
_USAGE_INTEGER_FIELDS = ("input_tokens_total", "output_tokens_total", "n_retries")
_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "backend_id",
        "backend_version",
        "latin_only",
        "data_origin",
        "request_hash",
        "answers",
        "captured_at_ms",
        "usage",
    }
)
_QUESTION_RECORD_FIELDS = frozenset({"name", "instructions", "options", "criteria"})
_RECORD_RESPONSE_FIELDS = frozenset({"answers", "usage", "captured_at_ms"})


def _is_trimmed_nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _check_choice_labels(choices: Mapping[str, Any]) -> None:
    for name, chosen in choices.items():
        if not _is_trimmed_nonempty(name):
            raise ValueError("stage answer names must be nonempty, trimmed strings.")
        if not _is_trimmed_nonempty(chosen):
            raise ValueError(
                f"stage answer {name!r} must be a nonempty, trimmed option label."
            )


def _check_usage(usage: object) -> None:
    if usage is None:
        return
    if not isinstance(usage, Mapping):
        raise TypeError("usage must be a mapping or null.")
    unknown = sorted(str(key) for key in usage if str(key) not in _USAGE_FIELDS)
    if unknown:
        raise ValueError(
            f"usage carries unsupported field(s) {unknown}; expected any of "
            f"{list(_USAGE_FIELDS)}."
        )
    for key, value in usage.items():
        name = str(key)
        if name in _USAGE_INTEGER_FIELDS:
            if type(value) is not int or value < 0:
                raise ValueError(f"usage.{name} must be a nonnegative integer.")
        elif not is_nonnegative_number(value):
            raise ValueError("usage.latency_ms must be a finite nonnegative number.")


def _check_answers(answers: object) -> None:
    if not isinstance(answers, Mapping) or not answers:
        raise ValueError("answers must be a non-empty mapping of question to answer.")
    for name, answer in answers.items():
        if not _is_trimmed_nonempty(name):
            raise ValueError("answer keys must be nonempty, trimmed question names.")
        if not isinstance(answer, Mapping):
            raise TypeError(f"the answer for {name!r} must be a mapping.")


@dataclass(frozen=True)
class OptionSetQuestion:
    """A closed option set, which may be wider than one call can offer.

    This is not a second question type: it is the declaration a caller makes
    before the option set is cut into stages that the reflex contract accepts.
    """

    name: str
    instructions: str
    options: tuple[str, ...]
    criteria: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.name):
            raise ValueError("name must be a nonempty, trimmed string.")
        if not _is_trimmed_nonempty(self.instructions):
            raise ValueError("instructions must be a nonempty, trimmed string.")
        if isinstance(self.options, (str, bytes)) or not isinstance(
            self.options, Sequence
        ):
            raise TypeError("options must be a sequence of option labels.")
        options = tuple(self.options)
        # Normalised so equality and hashing do not depend on the caller's
        # container, which matters when a fixture is compared to a plan.
        object.__setattr__(self, "options", options)
        if len(options) < 2:
            raise ValueError("an option set needs at least two options.")
        if len(options) > MAX_CHOICE_OPTIONS:
            raise ValueError(
                f"an option set is capped at {MAX_CHOICE_OPTIONS} options; above "
                "that the decision is refused instead of approximated."
            )
        seen: set[str] = set()
        for option in options:
            if not _is_trimmed_nonempty(option):
                raise ValueError("options must be nonempty, trimmed strings.")
            if option in seen:
                raise ValueError(f"options must not repeat {option!r}.")
            seen.add(option)
        if not isinstance(self.criteria, Mapping):
            raise TypeError("criteria must be a mapping of option to description.")
        unknown = sorted(str(key) for key in self.criteria if str(key) not in seen)
        if unknown:
            raise ValueError(f"criteria describe option(s) outside the set: {unknown}.")
        for key, value in self.criteria.items():
            if not _is_trimmed_nonempty(value):
                raise ValueError(
                    f"criteria[{key!r}] must be a nonempty, trimmed description."
                )

    @property
    def single_stage(self) -> bool:
        """Return whether one call can offer this whole option set."""
        return len(self.options) <= SINGLE_STAGE_CHOICE_CAP

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "instructions": self.instructions,
            "options": list(self.options),
            "criteria": {str(key): str(value) for key, value in self.criteria.items()},
        }


@dataclass(frozen=True)
class TwoStagePlan:
    """A deterministic cut of one option set into model-sized stages."""

    question_name: str
    options: tuple[str, ...]
    groups: tuple[tuple[str, ...], ...]
    max_stage_options: int

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.question_name):
            raise ValueError("question_name must be a nonempty, trimmed string.")
        if type(self.max_stage_options) is not int or not (
            2 <= self.max_stage_options <= SINGLE_STAGE_CHOICE_CAP
        ):
            raise ValueError(
                f"max_stage_options must be an integer in [2, {SINGLE_STAGE_CHOICE_CAP}]."
            )
        if not self.groups:
            raise ValueError("a plan needs at least one group.")
        flat = [option for group in self.groups for option in group]
        if sorted(flat) != sorted(self.options):
            raise ValueError("groups must partition the declared options exactly once.")
        for index, group in enumerate(self.groups, start=1):
            if len(group) < 2:
                raise ValueError(
                    f"group {index} holds {len(group)} option(s); a stage question "
                    "needs at least two."
                )
            if len(group) > self.max_stage_options:
                raise ValueError(
                    f"group {index} holds {len(group)} option(s), above "
                    f"max_stage_options={self.max_stage_options}."
                )
        if len(self.groups) > 1 and len(self.groups) > SINGLE_STAGE_CHOICE_CAP:
            raise ValueError(
                f"{len(self.groups)} groups would need a second stage above the "
                f"cap of {SINGLE_STAGE_CHOICE_CAP} candidates."
            )

    @property
    def decomposed(self) -> bool:
        """Return whether this plan needs a second stage."""
        return len(self.groups) > 1

    @property
    def stages(self) -> int:
        return 2 if self.decomposed else 1

    @property
    def total_options(self) -> int:
        return len(self.options)

    @property
    def final_question_name(self) -> str:
        return f"{self.question_name}.stage2"

    @property
    def final_stage_options(self) -> tuple[str, ...]:
        return tuple(f"g{index}" for index in range(1, len(self.groups) + 1))

    def group_question_name(self, index: int) -> str:
        if type(index) is not int or not 1 <= index <= len(self.groups):
            raise ValueError(
                f"group index must be an integer in [1, {len(self.groups)}]."
            )
        return f"{self.question_name}.stage1.g{index}"

    def stage_question_names(self) -> tuple[str, ...]:
        """Return the stage question names in evaluation order."""
        if not self.decomposed:
            return (self.question_name,)
        names = tuple(
            self.group_question_name(index)
            for index in range(1, len(self.groups) + 1)
        )
        return names + (self.final_question_name,)

    @property
    def stage_calls(self) -> int:
        """Return how many stage questions one decision needs."""
        return len(self.stage_question_names())

    @property
    def batched_round_trips(self) -> int:
        """Return the round trips a batched transport needs.

        Group questions share the state, so a transport that scores them from
        one cached context answers all of them in a single round trip; only the
        final question needs another. A transport that cannot batch needs as
        many round trips as there are stage calls.
        """
        return 2 if self.decomposed else 1

    def to_record(self) -> dict[str, Any]:
        return {
            "question_name": self.question_name,
            "total_options": self.total_options,
            "stages": self.stages,
            "groups": [list(group) for group in self.groups],
        }


def plan_two_stage(
    question: OptionSetQuestion,
    *,
    max_stage_options: int = SINGLE_STAGE_CHOICE_CAP,
) -> TwoStagePlan:
    """Cut one option set into balanced groups that respect the per-call cap.

    Groups are balanced rather than filled to the cap, so a remainder never
    produces a one-option group, which is not a valid choice question.
    """
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if type(max_stage_options) is not int or not (
        2 <= max_stage_options <= SINGLE_STAGE_CHOICE_CAP
    ):
        raise ValueError(
            f"max_stage_options must be an integer in [2, {SINGLE_STAGE_CHOICE_CAP}]."
        )
    options = question.options
    if len(options) <= max_stage_options:
        return TwoStagePlan(question.name, options, (options,), max_stage_options)

    count = -(-len(options) // max_stage_options)
    if count > SINGLE_STAGE_CHOICE_CAP:
        raise ValueError(
            f"{len(options)} options in stages of at most {max_stage_options} need "
            f"{count} second-stage candidates, above the cap of "
            f"{SINGLE_STAGE_CHOICE_CAP}: raise max_stage_options or shorten the "
            "option set."
        )
    base, extra = divmod(len(options), count)
    groups: list[tuple[str, ...]] = []
    cursor = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        groups.append(options[cursor : cursor + size])
        cursor += size
    return TwoStagePlan(question.name, options, tuple(groups), max_stage_options)


def _stage_criteria(
    question: OptionSetQuestion, options: Sequence[str]
) -> dict[str, str]:
    return {option: question.criteria.get(option, option) for option in options}


def stage_questions(
    plan: TwoStagePlan, question: OptionSetQuestion
) -> tuple[ReflexQuestion, ...]:
    """Build the reflex questions one plan implies, each within the cap."""
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if not isinstance(plan, TwoStagePlan):
        raise TypeError("plan must be a TwoStagePlan instance.")
    if plan.question_name != question.name or plan.options != question.options:
        raise ValueError("the plan was not built for this option set.")
    if not plan.decomposed:
        return (
            ReflexQuestion(
                question.name,
                ReflexKind.CHOICE,
                question.instructions,
                criteria=_stage_criteria(question, question.options),
            ),
        )
    questions: list[ReflexQuestion] = []
    for index, group in enumerate(plan.groups, start=1):
        questions.append(
            ReflexQuestion(
                plan.group_question_name(index),
                ReflexKind.CHOICE,
                f"{question.instructions} Group {index} of {len(plan.groups)}: "
                "pick the best option in this group.",
                criteria=_stage_criteria(question, group),
            )
        )
    questions.append(
        ReflexQuestion(
            plan.final_question_name,
            ReflexKind.CHOICE,
            f"{question.instructions} Final choice among {len(plan.groups)} "
            "group winners.",
            criteria={
                f"g{index}": f"winner of group {index}: " + ", ".join(group)
                for index, group in enumerate(plan.groups, start=1)
            },
        )
    )
    return tuple(questions)


@dataclass(frozen=True)
class TwoStageDecision:
    """One recomposed decision, or an explicit abstention."""

    question_name: str
    determined: bool
    winner: str | None
    total_options: int
    stages: int
    group_choices: Mapping[str, str]
    final_choice: str | None
    reason_code: str

    def __post_init__(self) -> None:
        if self.determined and self.winner is None:
            raise ValueError("a determined decision must name a winner.")
        if not self.determined and self.winner is not None:
            raise ValueError("an undetermined decision cannot name a winner.")

    def to_record(self) -> dict[str, Any]:
        return {
            "question_name": self.question_name,
            "determined": self.determined,
            "winner": self.winner,
            "total_options": self.total_options,
            "stages": self.stages,
            "group_choices": dict(self.group_choices),
            "final_choice": self.final_choice,
            "reason_code": self.reason_code,
        }


def compose_two_stage(
    question: OptionSetQuestion,
    plan: TwoStagePlan,
    choices: Mapping[str, str],
) -> TwoStageDecision:
    """Recombine stage answers into one decision, or abstain.

    A missing stage answer makes the decision undetermined: an unanswered
    question is not a zero score and not a default option. An answer outside
    the declared option set raises, because that is a malformed answer rather
    than an incomplete one.
    """
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if not isinstance(plan, TwoStagePlan):
        raise TypeError("plan must be a TwoStagePlan instance.")
    if not isinstance(choices, Mapping):
        raise TypeError("choices must be a mapping of stage question name to option.")
    if plan.question_name != question.name or plan.options != question.options:
        raise ValueError("the plan was not built for this option set.")
    _check_choice_labels(choices)

    def undetermined(group_choices: Mapping[str, str]) -> TwoStageDecision:
        return TwoStageDecision(
            question_name=question.name,
            determined=False,
            winner=None,
            total_options=len(question.options),
            stages=plan.stages,
            group_choices=dict(group_choices),
            final_choice=None,
            reason_code=UNDETERMINED_INCOMPLETE,
        )

    if not plan.decomposed:
        chosen = choices.get(question.name)
        if chosen is None:
            return undetermined({})
        if chosen not in question.options:
            raise ValueError(
                f"stage answer {chosen!r} is not in the declared option set."
            )
        return TwoStageDecision(
            question_name=question.name,
            determined=True,
            winner=chosen,
            total_options=len(question.options),
            stages=1,
            group_choices={"g1": chosen},
            final_choice=None,
            reason_code=DECIDED_SINGLE_STAGE,
        )

    group_choices: dict[str, str] = {}
    for index, group in enumerate(plan.groups, start=1):
        chosen = choices.get(plan.group_question_name(index))
        if chosen is None:
            return undetermined(group_choices)
        if chosen not in group:
            raise ValueError(f"stage answer {chosen!r} is not in group g{index}.")
        group_choices[f"g{index}"] = chosen

    final_choice = choices.get(plan.final_question_name)
    if final_choice is None:
        return undetermined(group_choices)
    if final_choice not in plan.final_stage_options:
        raise ValueError(
            f"final answer {final_choice!r} is not one of "
            f"{list(plan.final_stage_options)}."
        )
    return TwoStageDecision(
        question_name=question.name,
        determined=True,
        winner=group_choices[final_choice],
        total_options=len(question.options),
        stages=2,
        group_choices=group_choices,
        final_choice=final_choice,
        reason_code=DECIDED_TWO_STAGE,
    )


def _question_from_record(record: Any) -> OptionSetQuestion:
    if not isinstance(record, Mapping) or set(record) != _QUESTION_RECORD_FIELDS:
        raise ValueError(
            f"question must contain exactly {sorted(_QUESTION_RECORD_FIELDS)}."
        )
    options = record["options"]
    if not isinstance(options, list):
        raise ValueError("question.options must be a list.")
    criteria = record["criteria"]
    if criteria is None:
        criteria = {}
    if not isinstance(criteria, Mapping):
        raise ValueError("question.criteria must be a mapping or null.")
    return OptionSetQuestion(
        name=record["name"],
        instructions=record["instructions"],
        options=tuple(options),
        criteria={str(key): str(value) for key, value in criteria.items()},
    )


def two_stage_verifier(payload: Any) -> bool:
    """Accept a claimed decision only if recomposition reproduces it.

    A malformed payload raises, which the verifier registry reports as an
    abstention. A well-formed payload whose recomposition is undetermined, or
    whose claim disagrees with it, is rejected.
    """
    if not isinstance(payload, Mapping) or set(payload) != {
        "question",
        "max_stage_options",
        "choices",
        "claimed_winner",
    }:
        raise ValueError(
            "payload must contain exactly question, max_stage_options, choices "
            "and claimed_winner."
        )
    question = _question_from_record(payload["question"])
    plan = plan_two_stage(question, max_stage_options=payload["max_stage_options"])
    try:
        decision = compose_two_stage(question, plan, payload["choices"])
    except ValueError:
        # The payload is well formed and the claim contradicts it: that is a
        # rejection, not a reason to abstain.
        return False
    if not decision.determined:
        return False
    return decision.winner == payload["claimed_winner"]


def register_decision_verifiers(registry: VerifierRegistry) -> None:
    """Register the deterministic recomposition verifier under its identity."""
    if not isinstance(registry, VerifierRegistry):
        raise TypeError("registry must be a VerifierRegistry instance.")
    registry.register(DECISION_VERIFIER_ID, DECISION_VERIFIER_VERSION, two_stage_verifier)
    registry.register(SCORED_VERIFIER_ID, SCORED_VERIFIER_VERSION, scored_verifier)
    registry.register(SCHEMA_VERIFIER_ID, SCHEMA_VERIFIER_VERSION, schema_verifier)


def _question_payload(question: ReflexQuestion) -> dict[str, Any]:
    criteria: Any
    if isinstance(question.criteria, Mapping):
        criteria = {str(key): str(value) for key, value in question.criteria.items()}
    elif isinstance(question.criteria, Sequence) and not isinstance(
        question.criteria, (str, bytes)
    ):
        criteria = [str(level) for level in question.criteria]
    else:
        criteria = None
    return {
        "name": question.name,
        "kind": question.kind.value,
        "instructions": question.instructions,
        "criteria": criteria,
    }


@dataclass(frozen=True)
class DecisionRequest:
    """One typed-decision request, built before anything is called.

    The state age and the budget are part of the request because a decision is
    only meaningful against a snapshot and a deadline: both are inputs, not
    context a caller may add later.
    """

    request_id: str
    state: str
    questions: tuple[ReflexQuestion, ...]
    state_age_ms: float | None = None
    budget: DecisionBudget | None = None
    backend_id: str | None = None
    backend_version: str | None = None

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.request_id):
            raise ValueError("request_id must be a nonempty, trimmed string.")
        if not isinstance(self.state, str):
            raise TypeError("state must be a string.")
        if isinstance(self.questions, (str, bytes)) or not isinstance(
            self.questions, Sequence
        ):
            raise TypeError("questions must be a sequence of ReflexQuestion.")
        questions = tuple(self.questions)
        object.__setattr__(self, "questions", questions)
        if not questions:
            raise ValueError("a request needs at least one question.")
        if not all(isinstance(question, ReflexQuestion) for question in questions):
            raise TypeError("questions must contain ReflexQuestion instances.")
        names = [question.name for question in questions]
        if len(set(names)) != len(names):
            raise ValueError("question names must be unique within a request.")
        if self.state_age_ms is not None and not is_nonnegative_number(
            self.state_age_ms
        ):
            raise ValueError(
                "state_age_ms must be null or a finite nonnegative number."
            )
        if self.budget is not None and not isinstance(self.budget, DecisionBudget):
            raise TypeError("budget must be a DecisionBudget instance or null.")
        pinned = (self.backend_id, self.backend_version)
        if any(value is not None for value in pinned):
            if not all(_is_trimmed_nonempty(value) for value in pinned):
                raise ValueError(
                    "a pinned backend needs both backend_id and backend_version; a "
                    "name without a version is not provenance."
                )

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-serialisable envelope a transport would send."""
        backend = None
        if self.backend_id is not None:
            backend = {
                "backend_id": self.backend_id,
                "backend_version": self.backend_version,
            }
        return {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "state": self.state,
            "state_age_ms": self.state_age_ms,
            "questions": [_question_payload(question) for question in self.questions],
            "backend": backend,
        }

    def fingerprint(self) -> str:
        """Return the hash a recorded response must carry to be replayed.

        The budget belongs to the identity even though it is not sent to the
        backend: a decision taken under a different deadline is a different
        commitment, and a record captured under another deadline must not be
        replayed as if it answered this request.
        """
        identity = self.to_payload()
        identity["budget"] = (
            None
            if self.budget is None
            else {
                "budget_ms": self.budget.budget_ms,
                "max_state_age_ms": self.budget.max_state_age_ms,
                "fallback_route_id": self.budget.fallback_route_id,
            }
        )
        return hash_input(identity)


@dataclass(frozen=True)
class DecisionRecord:
    """One captured decision response plus the provenance that replays it.

    latin_only is recorded because it changes the outcome: it is a property of
    the backend that produced the answer, not of the replay.
    """

    backend_id: str
    backend_version: str
    request_hash: str
    answers: Mapping[str, Mapping[str, Any]]
    latin_only: bool = False
    data_origin: str = "recorded"
    captured_at_ms: float | None = None
    usage: Mapping[str, Any] | None = None
    schema_version: int = RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("backend_id", "backend_version"):
            if not _is_trimmed_nonempty(getattr(self, name)):
                raise ValueError(f"{name} must be a nonempty, trimmed string.")
        if (
            type(self.schema_version) is not int
            or self.schema_version != RECORD_SCHEMA_VERSION
        ):
            raise ValueError(
                f"Unsupported record schema_version; expected {RECORD_SCHEMA_VERSION}."
            )
        if (
            not isinstance(self.request_hash, str)
            or len(self.request_hash) != 64
            or any(
                character not in "0123456789abcdef" for character in self.request_hash
            )
        ):
            raise ValueError("request_hash must be 64 lowercase hexadecimal characters.")
        _check_answers(self.answers)
        if type(self.latin_only) is not bool:
            raise TypeError("latin_only must be a boolean.")
        if self.data_origin not in DATA_ORIGINS:
            raise ValueError(f"data_origin must be one of {list(DATA_ORIGINS)}.")
        if self.captured_at_ms is not None and not is_nonnegative_number(
            self.captured_at_ms
        ):
            raise ValueError("captured_at_ms must be null or a finite nonnegative number.")
        _check_usage(self.usage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "latin_only": self.latin_only,
            "data_origin": self.data_origin,
            "request_hash": self.request_hash,
            "answers": {
                str(name): dict(answer) for name, answer in self.answers.items()
            },
            "captured_at_ms": self.captured_at_ms,
            "usage": None if self.usage is None else dict(self.usage),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> "DecisionRecord":
        """Read a record strictly: an unknown or missing field is refused."""
        if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
            raise ValueError(
                f"a decision record must contain exactly {sorted(_RECORD_FIELDS)}."
            )
        return cls(
            backend_id=record["backend_id"],
            backend_version=record["backend_version"],
            request_hash=record["request_hash"],
            answers=record["answers"],
            latin_only=record["latin_only"],
            data_origin=record["data_origin"],
            captured_at_ms=record["captured_at_ms"],
            usage=record["usage"],
            schema_version=record["schema_version"],
        )


@dataclass(frozen=True)
class DecisionReplay:
    """Outcome of replaying one recorded response, plus its timing verdict."""

    status: str
    detail_code: str
    record: DecisionRecord
    batch: ReflexBatch | None = None
    timing: TimingVerdict | None = None

    def __post_init__(self) -> None:
        if self.status not in (
            "ok",
            "request_mismatch",
            "backend_mismatch",
            "incomplete",
        ):
            raise ValueError(
                "status must be ok, request_mismatch, backend_mismatch or incomplete."
            )
        if self.status == "ok" and self.batch is None:
            raise ValueError("an ok replay must carry the evaluated batch.")
        if self.status != "ok" and self.batch is not None:
            raise ValueError("only an ok replay may carry a batch.")

    @property
    def performed(self) -> bool:
        """Return whether the record matched the request and yielded answers."""
        return self.status == "ok"

    @property
    def usable(self) -> bool:
        """Return whether the consumer may use the replayed decision."""
        if not self.performed:
            return False
        return self.timing is None or self.timing.usable


def replay_decision(
    record: DecisionRecord,
    request: DecisionRequest,
    *,
    calibration: Any = None,
    timing: DecisionTiming | None = None,
) -> DecisionReplay:
    """Replay a recorded response offline, refusing a record that does not fit.

    No model is called. A record that answers a different request, or came from
    a different backend version than the one the request pinned, is refused
    rather than reinterpreted.
    """
    if not isinstance(record, DecisionRecord):
        raise TypeError("record must be a DecisionRecord instance.")
    if not isinstance(request, DecisionRequest):
        raise TypeError("request must be a DecisionRequest instance.")
    if timing is not None:
        if not isinstance(timing, DecisionTiming):
            raise TypeError("timing must be a DecisionTiming instance or null.")
        if request.budget is None:
            raise ValueError("a timing verdict needs a declared budget on the request.")

    if record.request_hash != request.fingerprint():
        return DecisionReplay("request_mismatch", "request_hash_mismatch", record)
    if request.backend_id is not None and record.backend_id != request.backend_id:
        return DecisionReplay("backend_mismatch", "backend_id_mismatch", record)
    if (
        request.backend_version is not None
        and record.backend_version != request.backend_version
    ):
        return DecisionReplay("backend_mismatch", "backend_version_mismatch", record)

    engine = ReflexEngine(
        InjectedReflexBackend(
            answers={
                str(name): dict(answer) for name, answer in record.answers.items()
            },
            latin_only=record.latin_only,
        )
    )
    try:
        batch = engine.evaluate(
            request.state, list(request.questions), calibration=calibration
        )
    except KeyError:
        return DecisionReplay("incomplete", "missing_answer", record)

    verdict = None
    if timing is not None and request.budget is not None:
        verdict = assess_decision_timing(request.budget, timing)
    return DecisionReplay("ok", "replayed", record, batch=batch, timing=verdict)


@dataclass(frozen=True)
class DecisionCapture:
    """Outcome of one attempted capture through a caller-supplied transport."""

    status: str
    detail_code: str
    request: DecisionRequest
    record: DecisionRecord | None = None
    replay: DecisionReplay | None = None

    def __post_init__(self) -> None:
        if self.status not in ("ok", "unavailable", "error"):
            raise ValueError("status must be ok, unavailable or error.")
        if self.status == "ok" and (self.record is None or self.replay is None):
            raise ValueError("an ok capture must carry a record and its replay.")
        if self.status != "ok" and self.record is not None:
            raise ValueError("only an ok capture may carry a record.")
        if not isinstance(self.detail_code, str) or not self.detail_code.strip():
            raise ValueError("detail_code must be a nonempty string.")

    @property
    def performed(self) -> bool:
        """Return whether a response was captured and replayed."""
        return self.status == "ok"

    @property
    def usable(self) -> bool:
        """Return whether the captured decision may be used as it stands."""
        return self.performed and self.replay is not None and self.replay.usable


def _record_from_response(
    payload: Any,
    *,
    request: DecisionRequest,
    backend_id: str,
    backend_version: str,
    latin_only: bool,
    captured_at_ms: float | None,
    data_origin: str,
) -> DecisionRecord:
    if not isinstance(payload, Mapping):
        raise TypeError("a transport must return a mapping.")
    unknown = sorted(
        str(key) for key in payload if str(key) not in _RECORD_RESPONSE_FIELDS
    )
    if unknown:
        raise ValueError(
            f"a captured response carries unsupported field(s) {unknown}; expected "
            f"any of {sorted(_RECORD_RESPONSE_FIELDS)}."
        )
    if "answers" not in payload:
        raise ValueError("a captured response must carry an answers mapping.")
    stamp = captured_at_ms
    if stamp is None:
        stamp = payload.get("captured_at_ms")
    return DecisionRecord(
        backend_id=backend_id,
        backend_version=backend_version,
        request_hash=request.fingerprint(),
        answers=payload["answers"],
        latin_only=latin_only,
        data_origin=data_origin,
        captured_at_ms=stamp,
        usage=payload.get("usage"),
    )


def capture_decision(
    request: DecisionRequest,
    *,
    backend_id: str,
    backend_version: str,
    transport: Callable[[Mapping[str, Any]], object] | None = None,
    latin_only: bool = False,
    captured_at_ms: float | None = None,
    timing: DecisionTiming | None = None,
    calibration: Any = None,
) -> DecisionCapture:
    """Capture one decision through an injected transport, then replay it.

    The library performs no network I/O of its own: the caller supplies the
    transport, and its absence is a typed unavailable capture. That transport is
    the only piece a real decision-model call still needs.
    """
    if not isinstance(request, DecisionRequest):
        raise TypeError("request must be a DecisionRequest instance.")
    for name, value in (
        ("backend_id", backend_id),
        ("backend_version", backend_version),
    ):
        if not _is_trimmed_nonempty(value):
            raise ValueError(f"{name} must be a nonempty, trimmed string.")
    if request.backend_id is not None and request.backend_id != backend_id:
        raise ValueError(
            f"this request pins backend {request.backend_id!r}; a capture from "
            f"{backend_id!r} would not be replayable against it."
        )
    if request.backend_version is not None and request.backend_version != backend_version:
        raise ValueError(
            f"this request pins backend version {request.backend_version!r}; a "
            f"capture from version {backend_version!r} would not be replayable."
        )
    if transport is None:
        return DecisionCapture("unavailable", "no_transport_configured", request)
    if not callable(transport):
        raise TypeError("transport must be callable.")

    payload = request.to_payload()
    try:
        response = transport(payload)
    except OSError:
        return DecisionCapture("unavailable", "transport_unavailable", request)
    except Exception as exc:  # noqa: BLE001 - reported as a typed error
        return DecisionCapture("error", f"transport_error:{type(exc).__name__}", request)
    try:
        record = _record_from_response(
            response,
            request=request,
            backend_id=backend_id,
            backend_version=backend_version,
            latin_only=latin_only,
            captured_at_ms=captured_at_ms,
            data_origin="recorded",
        )
    except (TypeError, ValueError):
        return DecisionCapture("error", "invalid_response", request)

    replay = replay_decision(record, request, calibration=calibration, timing=timing)
    if not replay.performed:
        return DecisionCapture("error", replay.detail_code, request)
    return DecisionCapture("ok", "captured", request, record=record, replay=replay)


def decision_route_entry(
    *,
    estimated_cost: float | None,
    route_id: str = "route.decision.typed",
    estimated_latency_ms: float | None = None,
    confidence: float | None = None,
    risk_classes: Sequence[str] = ("low",),
    evidence_levels: Sequence[str] = ("normal",),
    localities: Sequence[str] = ("any", "local"),
    verifier_id: str = DECISION_VERIFIER_ID,
    verifier_version: str = DECISION_VERIFIER_VERSION,
) -> dict[str, Any]:
    """Build the manifest entry for this route, without inventing its estimates.

    estimated_cost has no default on purpose: a route's cost is a measured
    value or a declared estimate, never a guess made here. confidence stays None
    until the decision is calibrated on this repository's tasks.
    """
    return {
        "route_id": route_id,
        "capability_ids": [DECISION_CAPABILITY],
        "estimated_cost": estimated_cost,
        "estimated_latency_ms": estimated_latency_ms,
        "confidence": confidence,
        "constraints": {
            "risk_classes": list(risk_classes),
            "evidence_levels": list(evidence_levels),
            "localities": list(localities),
        },
        "verifier": {"verifier_id": verifier_id, "verifier_version": verifier_version},
    }


#: Policy knobs of the scored mode, declared rather than measured: how many
#: options the explicit second-stage choice is offered, and how many questions
#: one scoring call may carry.
DEFAULT_FINALISTS = 8
DEFAULT_QUESTIONS_PER_CALL = 64

DECIDED_SCORED = "scored_then_chosen"
UNDETERMINED_SCORES = "incomplete_scores"
UNDETERMINED_FINAL = "incomplete_final_choice"


def _rank_options(
    scores: Mapping[str, float], options: Sequence[str]
) -> tuple[str, ...]:
    """Rank options by score, breaking ties by declared order."""
    order = {option: index for index, option in enumerate(options)}
    return tuple(sorted(options, key=lambda option: (-scores[option], order[option])))


def _check_scores(scores: object, options: Sequence[str]) -> None:
    if not isinstance(scores, Mapping):
        raise TypeError("scores must be a mapping of option to score.")
    known = set(options)
    for option, value in scores.items():
        if option not in known:
            raise ValueError(
                f"a score for {option!r} refers to an option outside the declared set."
            )
        if not is_nonnegative_number(value) or value > 1.0:
            raise ValueError(
                f"the score for {option!r} must be a finite number in [0, 1]."
            )


@dataclass(frozen=True)
class ScoredPlan:
    """Independent per-option scoring, then one explicit choice.

    Every option gets its own boolean question, so a score is not conditioned on
    the other options of a batch and the resulting vector stays comparable
    across batches. The final choice is then asked over the highest-scoring
    options only, so the second stage never exceeds the choice cap.

    The second stage cannot be built before the scores exist, which is why a
    scored decision is two requests rather than one.
    """

    question_name: str
    options: tuple[str, ...]
    score_batches: tuple[tuple[str, ...], ...]
    finalists: int
    max_questions_per_call: int

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.question_name):
            raise ValueError("question_name must be a nonempty, trimmed string.")
        if type(self.max_questions_per_call) is not int or not (
            1 <= self.max_questions_per_call <= MAX_CHOICE_OPTIONS
        ):
            raise ValueError(
                "max_questions_per_call must be an integer in "
                f"[1, {MAX_CHOICE_OPTIONS}]."
            )
        if not self.score_batches:
            raise ValueError("a scored plan needs at least one scoring batch.")
        flat = [option for batch in self.score_batches for option in batch]
        if sorted(flat) != sorted(self.options):
            raise ValueError(
                "score batches must partition the declared options exactly once."
            )
        for index, batch in enumerate(self.score_batches, start=1):
            if not 1 <= len(batch) <= self.max_questions_per_call:
                raise ValueError(
                    f"scoring batch {index} holds {len(batch)} option(s), above "
                    f"max_questions_per_call={self.max_questions_per_call}."
                )
        if type(self.finalists) is not int or not (
            2 <= self.finalists <= SINGLE_STAGE_CHOICE_CAP
        ):
            raise ValueError(
                f"finalists must be an integer in [2, {SINGLE_STAGE_CHOICE_CAP}]."
            )
        if self.finalists > len(self.options):
            raise ValueError(
                f"finalists={self.finalists} exceeds the {len(self.options)} "
                "declared options."
            )

    @property
    def total_options(self) -> int:
        return len(self.options)

    @property
    def score_calls(self) -> int:
        return len(self.score_batches)

    @property
    def stage_calls(self) -> int:
        """Return the scoring calls plus the explicit final choice."""
        return len(self.score_batches) + 1

    @property
    def batched_round_trips(self) -> int:
        """Return the round trips a batched transport needs.

        Every scoring batch shares one cached context, so all of them cost one
        round trip; the final question depends on their result and needs its own.
        A transport that cannot batch needs as many round trips as stage calls.
        """
        return 2

    @property
    def final_question_name(self) -> str:
        return f"{self.question_name}.final"

    def score_question_name(self, index: int) -> str:
        if type(index) is not int or not 1 <= index <= len(self.options):
            raise ValueError(
                f"option index must be an integer in [1, {len(self.options)}]."
            )
        return f"{self.question_name}.score.o{index}"

    def option_index(self, option: str) -> int:
        for index, candidate in enumerate(self.options, start=1):
            if candidate == option:
                return index
        raise ValueError(f"unknown option {option!r}.")

    def stage_question_names(self) -> tuple[str, ...]:
        """Return the scoring question names, then the final question name."""
        names = tuple(
            self.score_question_name(index)
            for index in range(1, len(self.options) + 1)
        )
        return names + (self.final_question_name,)

    def to_record(self) -> dict[str, Any]:
        return {
            "question_name": self.question_name,
            "total_options": self.total_options,
            "finalists": self.finalists,
            "score_calls": self.score_calls,
            "batched_round_trips": self.batched_round_trips,
        }


def plan_scored_stages(
    question: OptionSetQuestion,
    *,
    finalists: int = DEFAULT_FINALISTS,
    max_questions_per_call: int = DEFAULT_QUESTIONS_PER_CALL,
) -> ScoredPlan:
    """Plan independent scoring of every option, then one explicit choice."""
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if type(finalists) is not int or not (2 <= finalists <= SINGLE_STAGE_CHOICE_CAP):
        raise ValueError(
            f"finalists must be an integer in [2, {SINGLE_STAGE_CHOICE_CAP}]."
        )
    if type(max_questions_per_call) is not int or not (
        1 <= max_questions_per_call <= MAX_CHOICE_OPTIONS
    ):
        raise ValueError(
            "max_questions_per_call must be an integer in "
            f"[1, {MAX_CHOICE_OPTIONS}]."
        )
    options = question.options
    if finalists > len(options):
        raise ValueError(
            f"finalists={finalists} exceeds the {len(options)} declared options."
        )
    size = min(max_questions_per_call, len(options))
    batches = tuple(
        options[start : start + size] for start in range(0, len(options), size)
    )
    return ScoredPlan(question.name, options, batches, finalists, size)


def scored_stage_questions(
    plan: ScoredPlan, question: OptionSetQuestion
) -> tuple[ReflexQuestion, ...]:
    """Build one boolean question per option, in declared order.

    These are the questions of the first request. The final choice is built from
    the scores by finalist_question, because its option set does not exist yet.
    """
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if not isinstance(plan, ScoredPlan):
        raise TypeError("plan must be a ScoredPlan instance.")
    if plan.question_name != question.name or plan.options != question.options:
        raise ValueError("the plan was not built for this option set.")
    questions: list[ReflexQuestion] = []
    for option in question.options:
        index = plan.option_index(option)
        questions.append(
            ReflexQuestion(
                plan.score_question_name(index),
                ReflexKind.NOUL,
                f"{question.instructions} Does this option satisfy it: "
                f"{question.criteria.get(option, option)}?",
            )
        )
    return tuple(questions)


def finalist_question(
    question: OptionSetQuestion,
    plan: ScoredPlan,
    scores: Mapping[str, float],
) -> ReflexQuestion:
    """Build the explicit second-stage choice over the top-scoring options.

    An incomplete score vector is refused here rather than ranked with a missing
    value treated as zero.
    """
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if not isinstance(plan, ScoredPlan):
        raise TypeError("plan must be a ScoredPlan instance.")
    if plan.question_name != question.name or plan.options != question.options:
        raise ValueError("the plan was not built for this option set.")
    _check_scores(scores, question.options)
    missing = [option for option in question.options if option not in scores]
    if missing:
        raise ValueError(
            f"the score vector is incomplete: {len(missing)} option(s) are not "
            "scored, and a missing score is never zero."
        )
    finalists = _rank_options(scores, question.options)[: plan.finalists]
    return ReflexQuestion(
        plan.final_question_name,
        ReflexKind.CHOICE,
        f"{question.instructions} Final choice among the {len(finalists)} "
        "highest-scoring options.",
        criteria={option: question.criteria.get(option, option) for option in finalists},
    )


@dataclass(frozen=True)
class ScoredDecision:
    """One decision taken by scoring every option, then choosing explicitly."""

    question_name: str
    determined: bool
    winner: str | None
    total_options: int
    score_calls: int
    scores: Mapping[str, float]
    finalists: tuple[str, ...]
    tie_at_cutoff: bool
    argmax_agrees: bool
    reason_code: str

    def __post_init__(self) -> None:
        if self.determined and self.winner is None:
            raise ValueError("a determined decision must name a winner.")
        if not self.determined and self.winner is not None:
            raise ValueError("an undetermined decision cannot name a winner.")

    def to_record(self) -> dict[str, Any]:
        return {
            "question_name": self.question_name,
            "determined": self.determined,
            "winner": self.winner,
            "total_options": self.total_options,
            "score_calls": self.score_calls,
            "scores": {str(key): value for key, value in self.scores.items()},
            "finalists": list(self.finalists),
            "tie_at_cutoff": self.tie_at_cutoff,
            "argmax_agrees": self.argmax_agrees,
            "reason_code": self.reason_code,
        }


def compose_scored(
    question: OptionSetQuestion,
    plan: ScoredPlan,
    scores: Mapping[str, float],
    final_choice: str | None = None,
) -> ScoredDecision:
    """Recombine a score vector and an explicit choice into one decision.

    A missing score makes the decision undetermined, and so does a missing
    explicit choice. A choice outside the declared options, or outside the
    recomputed finalists, raises: the second-stage question only offered the
    finalists, so a different answer is malformed rather than merely wrong.
    """
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if not isinstance(plan, ScoredPlan):
        raise TypeError("plan must be a ScoredPlan instance.")
    if plan.question_name != question.name or plan.options != question.options:
        raise ValueError("the plan was not built for this option set.")
    _check_scores(scores, question.options)

    options = question.options
    missing = [option for option in options if option not in scores]
    ranked = (
        _rank_options({option: scores[option] for option in options}, options)
        if not missing
        else ()
    )
    finalists = ranked[: plan.finalists]
    scored = {str(key): float(value) for key, value in scores.items()}

    def undetermined(reason_code: str) -> ScoredDecision:
        return ScoredDecision(
            question_name=question.name,
            determined=False,
            winner=None,
            total_options=len(options),
            score_calls=plan.score_calls,
            scores=scored,
            finalists=tuple(finalists),
            tie_at_cutoff=False,
            argmax_agrees=False,
            reason_code=reason_code,
        )

    if missing:
        return undetermined(UNDETERMINED_SCORES)
    if final_choice is None:
        return undetermined(UNDETERMINED_FINAL)
    if final_choice not in options:
        raise ValueError(f"the chosen option {final_choice!r} was never declared.")
    if final_choice not in finalists:
        raise ValueError(
            f"the chosen option {final_choice!r} is not among the "
            f"{len(finalists)} scored finalists."
        )
    cutoff = scores[finalists[-1]]
    return ScoredDecision(
        question_name=question.name,
        determined=True,
        winner=final_choice,
        total_options=len(options),
        score_calls=plan.score_calls,
        scores=scored,
        finalists=tuple(finalists),
        tie_at_cutoff=any(
            scores[option] == cutoff for option in ranked[plan.finalists :]
        ),
        argmax_agrees=final_choice == finalists[0],
        reason_code=DECIDED_SCORED,
    )


def scored_verifier(payload: Any) -> bool:
    """Accept a claimed choice only if the recorded scores still support it.

    The payload is well formed by construction, so a claim that is outside the
    declared options, or outside the finalists recomputed from the recorded
    scores, is rejected. Only a structurally invalid payload raises.
    """
    expected = {
        "question",
        "finalists",
        "max_questions_per_call",
        "scores",
        "claimed_winner",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError(f"payload must contain exactly {sorted(expected)}.")
    question = _question_from_record(payload["question"])
    plan = plan_scored_stages(
        question,
        finalists=payload["finalists"],
        max_questions_per_call=payload["max_questions_per_call"],
    )
    claimed_winner = payload["claimed_winner"]
    if claimed_winner is not None and not isinstance(claimed_winner, str):
        raise ValueError("claimed_winner must be a string or null.")
    try:
        decision = compose_scored(question, plan, payload["scores"], claimed_winner)
    except ValueError:
        return False
    return decision.determined


_REQUEST_PAYLOAD_FIELDS = frozenset(
    {"schema_version", "request_id", "state", "state_age_ms", "questions", "backend"}
)


def _reflex_question_from_payload(item: Any) -> ReflexQuestion:
    if not isinstance(item, Mapping) or set(item) != {
        "name",
        "kind",
        "instructions",
        "criteria",
    }:
        raise ValueError(
            "a recorded question must contain exactly name, kind, instructions "
            "and criteria."
        )
    kind = item["kind"]
    if not isinstance(kind, str):
        raise ValueError("a recorded question kind must be a string.")
    try:
        reflex_kind = ReflexKind(kind)
    except ValueError as exc:
        raise ValueError(f"unknown question kind {kind!r}.") from exc
    return ReflexQuestion(
        name=item["name"],
        kind=reflex_kind,
        instructions=item["instructions"],
        criteria=item["criteria"],
    )


def _request_from_payload(payload: Any) -> DecisionRequest:
    """Rebuild a request from the envelope a backend received.

    The budget is not part of that envelope, so a rebuilt request carries none:
    it answers shape and identity questions, not admissibility ones.
    """
    if not isinstance(payload, Mapping) or set(payload) != _REQUEST_PAYLOAD_FIELDS:
        raise ValueError(
            f"request must contain exactly {sorted(_REQUEST_PAYLOAD_FIELDS)}."
        )
    if payload["schema_version"] != REQUEST_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported request schema_version; expected {REQUEST_SCHEMA_VERSION}."
        )
    raw_questions = payload["questions"]
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError("request.questions must be a non-empty list.")
    backend = payload["backend"]
    backend_id = None
    backend_version = None
    if backend is not None:
        if not isinstance(backend, Mapping) or set(backend) != {
            "backend_id",
            "backend_version",
        }:
            raise ValueError(
                "request.backend must carry exactly backend_id and backend_version."
            )
        backend_id = backend["backend_id"]
        backend_version = backend["backend_version"]
    return DecisionRequest(
        request_id=payload["request_id"],
        state=payload["state"],
        questions=tuple(_reflex_question_from_payload(item) for item in raw_questions),
        state_age_ms=payload["state_age_ms"],
        backend_id=backend_id,
        backend_version=backend_version,
    )


def schema_verifier(payload: Any) -> bool:
    """Accept a recorded response only if it fits the request it answers.

    This is conformance, not correctness: a well-typed answer can still be the
    wrong answer, which is a calibration failure rather than a schema one. A
    structurally invalid payload raises. A response that misses an answer,
    carries an extra one, or breaks the declared shape is rejected.
    """
    if not isinstance(payload, Mapping) or set(payload) != {"request", "answers"}:
        raise ValueError("payload must contain exactly request and answers.")
    request = _request_from_payload(payload["request"])
    answers = payload["answers"]
    if not isinstance(answers, Mapping):
        raise ValueError("answers must be a mapping of question name to answer.")
    if set(answers) != {question.name for question in request.questions}:
        return False
    engine = ReflexEngine(
        InjectedReflexBackend(
            answers={
                str(name): dict(answer)
                for name, answer in answers.items()
                if isinstance(answer, Mapping)
            },
            latin_only=False,
        )
    )
    try:
        engine.evaluate(request.state, list(request.questions))
    except (KeyError, TypeError, ValueError):
        return False
    return True


def two_stage_payload(
    question: OptionSetQuestion,
    choices: Mapping[str, str],
    claimed_winner: str | None,
    *,
    max_stage_options: int = SINGLE_STAGE_CHOICE_CAP,
) -> dict[str, Any]:
    """Build the payload the two-stage verifier expects."""
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if not isinstance(choices, Mapping):
        raise TypeError("choices must be a mapping of stage question name to option.")
    return {
        "question": question.to_record(),
        "max_stage_options": max_stage_options,
        "choices": {str(name): str(choice) for name, choice in choices.items()},
        "claimed_winner": claimed_winner,
    }


def scored_payload(
    question: OptionSetQuestion,
    scores: Mapping[str, float],
    claimed_winner: str | None,
    *,
    finalists: int = DEFAULT_FINALISTS,
    max_questions_per_call: int = DEFAULT_QUESTIONS_PER_CALL,
) -> dict[str, Any]:
    """Build the payload the scored verifier expects."""
    if not isinstance(question, OptionSetQuestion):
        raise TypeError("question must be an OptionSetQuestion instance.")
    if not isinstance(scores, Mapping):
        raise TypeError("scores must be a mapping of option to score.")
    return {
        "question": question.to_record(),
        "finalists": finalists,
        "max_questions_per_call": max_questions_per_call,
        "scores": {str(option): value for option, value in scores.items()},
        "claimed_winner": claimed_winner,
    }


def schema_payload(request: DecisionRequest, record: DecisionRecord) -> dict[str, Any]:
    """Build the payload the schema verifier expects."""
    if not isinstance(request, DecisionRequest):
        raise TypeError("request must be a DecisionRequest instance.")
    if not isinstance(record, DecisionRecord):
        raise TypeError("record must be a DecisionRecord instance.")
    return {
        "request": request.to_payload(),
        "answers": {str(name): dict(answer) for name, answer in record.answers.items()},
    }


def write_decision_record(path: str | Path, record: DecisionRecord) -> None:
    """Write one recorded response without overwriting an existing file."""
    if not isinstance(record, DecisionRecord):
        raise TypeError("record must be a DecisionRecord instance.")
    envelope = {"kind": DECISION_RECORD_KIND, "record": record.to_dict()}
    payload = json.dumps(envelope, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)


def read_decision_record(path: str | Path) -> DecisionRecord:
    """Read one recorded response, rejecting malformed or ambiguous JSON."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        envelope = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ValueError as exc:
        raise ValueError(f"Decision record file is not valid JSON: {exc}") from exc
    if not isinstance(envelope, Mapping) or set(envelope) != {"kind", "record"}:
        raise ValueError("a decision record file must contain exactly kind and record.")
    if envelope["kind"] != DECISION_RECORD_KIND:
        raise ValueError(f"kind must be {DECISION_RECORD_KIND!r}.")
    return DecisionRecord.from_dict(envelope["record"])


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite number {value!r} is not supported")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r} is not allowed")
        result[key] = value
    return result
