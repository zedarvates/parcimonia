"""Measure the static audit against an authored corpus.

A threshold is only as good as the evidence under it, so this module answers
two questions with numbers instead of opinions: how often each rule is right,
and whether the role suppressions actually suppress what they claim.

The corpus is authored, so its provenance is ``fixture``. A fixture report can
falsify a rule and it cannot authorise a threshold: a band, a weight or a
per-rule rate coming from authored examples is evidence about the analyser, not
about real code. The report carries that boundary explicitly instead of leaving
it to a reader to remember.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .audit import AuditRequest, audit_policy_version, audit_source
from .audit_corpus import BAND_CLASSES, LabelledAuditCase, audit_corpus
from .audit_score import ScoreWeights
from .pattern_rules import RuleRegistry, builtin_rule_registry

__all__ = [
    "AuditCalibrationReport",
    "CaseObservation",
    "RuleScore",
    "calibrate_static_audit",
]

#: Provenance values a calibration report may declare. Only a measured run on
#: real, human-labelled outcomes may carry ``measured``.
CALIBRATION_ORIGINS = frozenset({"fixture", "measured"})


@dataclass(frozen=True)
class CaseObservation:
    """What the corpus expected and what the audit actually reported."""

    case_id: str
    expected_role: str
    observed_role: str
    expected_band_class: str
    observed_band: str
    expected_rules: tuple[str, ...]
    observed_rules: tuple[str, ...]
    measured_deficit: float | None
    reason_code: str | None

    @property
    def role_ok(self) -> bool:
        return self.expected_role == self.observed_role

    @property
    def band_ok(self) -> bool:
        return self.observed_band in BAND_CLASSES[self.expected_band_class]

    @property
    def rules_ok(self) -> bool:
        return set(self.expected_rules) == set(self.observed_rules)

    @property
    def ok(self) -> bool:
        return self.role_ok and self.band_ok and self.rules_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_role": self.expected_role,
            "observed_role": self.observed_role,
            "expected_band_class": self.expected_band_class,
            "observed_band": self.observed_band,
            "expected_rules": list(self.expected_rules),
            "observed_rules": list(self.observed_rules),
            "measured_deficit": self.measured_deficit,
            "reason_code": self.reason_code,
            "role_ok": self.role_ok,
            "band_ok": self.band_ok,
            "rules_ok": self.rules_ok,
        }


@dataclass(frozen=True)
class RuleScore:
    """How one rule behaved on the corpus."""

    rule_id: str
    true_positives: int
    false_positives: int
    missed: int
    expected_in: int

    @property
    def fired_in(self) -> int:
        return self.true_positives + self.false_positives

    @property
    def precision(self) -> float | None:
        """Share of firings the corpus expected, or None when it never fired."""
        return None if self.fired_in == 0 else self.true_positives / self.fired_in

    @property
    def recall(self) -> float | None:
        """Share of expected firings that happened, or None when never expected."""
        return None if self.expected_in == 0 else self.true_positives / self.expected_in

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "missed": self.missed,
            "expected_in": self.expected_in,
            "precision": self.precision,
            "recall": self.recall,
        }


@dataclass(frozen=True)
class AuditCalibrationReport:
    """One calibration run, with the boundary that produced it."""

    data_origin: str
    policy_base: str
    policy_version: str
    rule_fingerprint: str
    declared_weights: Mapping[str, float]
    cases: tuple[CaseObservation, ...]
    per_rule: tuple[RuleScore, ...]
    threshold_authorized: bool = False

    def __post_init__(self) -> None:
        if self.data_origin not in CALIBRATION_ORIGINS:
            raise ValueError(f"unknown data_origin {self.data_origin!r}.")
        if self.threshold_authorized and self.data_origin != "measured":
            raise ValueError(
                "a threshold cannot be authorised by anything but measured, "
                "human-labelled outcomes."
            )

    @property
    def n_cases(self) -> int:
        return len(self.cases)

    @property
    def role_agreement(self) -> float:
        """Share of cases whose structural role matched the label."""
        return _share(self.cases, lambda item: item.role_ok)

    @property
    def band_agreement(self) -> float:
        """Share of cases whose band landed in the class the label allowed."""
        return _share(self.cases, lambda item: item.band_ok)

    @property
    def rule_agreement(self) -> float:
        """Share of cases whose fired rule set matched the label exactly."""
        return _share(self.cases, lambda item: item.rules_ok)

    @property
    def disagreements(self) -> tuple[CaseObservation, ...]:
        return tuple(item for item in self.cases if not item.ok)

    def authorizes_threshold(self) -> bool:
        """Return whether this run may gate execution. Only measured data may."""
        return self.threshold_authorized and self.data_origin == "measured"


    def to_record(self) -> dict[str, Any]:
        """Return the snapshot, with its boundary attached to it."""
        authorized = self.authorizes_threshold()
        return {
            "kind": "audit_calibration",
            "data_origin": self.data_origin,
            "policy_base": self.policy_base,
            "policy_version": self.policy_version,
            "rule_fingerprint": self.rule_fingerprint,
            "declared_weights": dict(self.declared_weights),
            "n_cases": self.n_cases,
            "role_agreement": self.role_agreement,
            "band_agreement": self.band_agreement,
            "rule_agreement": self.rule_agreement,
            "per_rule": [score.to_dict() for score in self.per_rule],
            "threshold_authorized": authorized,
            "threshold_authorized_reason": (
                "measured, human-labelled outcomes are required"
                if not authorized
                else "authorised by the operator on measured outcomes"
            ),
        }

    def case_records(self) -> list[dict[str, Any]]:
        """Return one record per case, for a report that can be inspected."""
        return [item.to_dict() for item in self.cases]


def _share(cases: Sequence[CaseObservation], predicate) -> float:
    """Return the share of cases satisfying a predicate, or 0.0 when empty."""
    if not cases:
        return 0.0
    return sum(1 for item in cases if predicate(item)) / len(cases)


def calibrate_static_audit(
    *,
    policy_base: str = "static-audit-v1",
    registry: RuleRegistry | None = None,
    weights: ScoreWeights | None = None,
    cases: Sequence[LabelledAuditCase] | None = None,
) -> AuditCalibrationReport:
    """Run the audit over the authored corpus and report per-rule behaviour.

    The origin is always ``fixture``: this harness measures authored examples, so
    it has no way to claim anything else, and no argument lets a caller pretend
    otherwise. A measured calibration needs measured, human-labelled outcomes and
    belongs in its own entry point.
    """
    active = registry if registry is not None else builtin_rule_registry()
    if not isinstance(active, RuleRegistry):
        raise TypeError("registry must be a RuleRegistry instance.")
    policy = audit_policy_version(policy_base, active)
    corpus = tuple(cases) if cases is not None else audit_corpus()
    if not corpus:
        raise ValueError("a calibration needs at least one labelled case.")

    observations = []
    for item in corpus:
        outcome = audit_source(
            AuditRequest(item.case_id, item.path, item.source),
            policy_version=policy,
            registry=active,
            weights=weights,
        )
        observations.append(
            CaseObservation(
                case_id=item.case_id,
                expected_role=item.role,
                observed_role=outcome.role,
                expected_band_class=item.band_class,
                observed_band=outcome.band,
                expected_rules=tuple(sorted(item.rules)),
                observed_rules=tuple(sorted(outcome.rule_counts)),
                measured_deficit=outcome.deficit,
                reason_code=outcome.reason_code,
            )
        )

    scores = tuple(
        _score_rule(rule.rule_id, observations) for rule in active.rules()
    )
    declared = (weights if weights is not None else ScoreWeights()).as_mapping()
    return AuditCalibrationReport(
        data_origin="fixture",
        policy_base=policy_base,
        policy_version=policy,
        rule_fingerprint=active.fingerprint(),
        declared_weights=declared,
        cases=tuple(observations),
        per_rule=scores,
        threshold_authorized=False,
    )


def _score_rule(rule_id: str, observations: Sequence[CaseObservation]) -> RuleScore:
    true_positives = 0
    false_positives = 0
    missed = 0
    expected_in = 0
    for item in observations:
        expected = rule_id in item.expected_rules
        observed = rule_id in item.observed_rules
        expected_in += 1 if expected else 0
        if expected and observed:
            true_positives += 1
        elif observed:
            false_positives += 1
        elif expected:
            missed += 1
    return RuleScore(rule_id, true_positives, false_positives, missed, expected_in)
