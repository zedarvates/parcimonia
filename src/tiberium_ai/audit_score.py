"""Pure deficit scoring for one deterministic static audit.

Four ratio dimensions in ``[0, 1]``, where 1 is best, are combined with a
weighted geometric mean and a capped additive penalty for discrete rule
findings. A geometric mean is used deliberately: one collapsed dimension cannot
be averaged away by three healthy ones, which is the failure mode of a plain
weighted sum. The deficit is then attributed back to its sources by log-loss
share so the number a caller acts on can explain itself.

The module is a set of pure functions over values that were already extracted.
It reads no file, no clock, no database and no network, and it never invents a
missing measurement: an unknown dimension is an error, and a suppressed
dimension must be declared as suppressed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from .pattern_rules import RuleFinding, RuleSeverity

__all__ = [
    "AuditBand",
    "AuditScore",
    "BAND_THRESHOLDS",
    "DIMENSION_NAMES",
    "DimensionValue",
    "EPSILON",
    "PATTERN_PENALTY_CAP",
    "SEVERITY_PENALTY",
    "ScoreWeights",
    "compute_audit_score",
]

#: Floor applied before a logarithm, so a dimension of exactly zero is scored as
#: near-zero instead of undefined.
EPSILON = 1e-4

#: The four dimensions a v1 audit measures, in report order.
DIMENSION_NAMES: tuple[str, ...] = (
    "substance",
    "structure_integrity",
    "documentation_balance",
    "import_hygiene",
)

#: Additive deficit contributed by one finding of each severity.
SEVERITY_PENALTY: Mapping[str, float] = {
    RuleSeverity.BLOCKER.value: 12.0,
    RuleSeverity.HIGH.value: 6.0,
    RuleSeverity.MEDIUM.value: 2.5,
    RuleSeverity.LOW.value: 1.0,
}

#: Ceiling on what repeated discrete findings can add on their own, so a single
#: repeated defect cannot drive the whole verdict.
PATTERN_PENALTY_CAP = 40.0

#: Deficit thresholds, highest first. A deficit below the last one is sound.
BAND_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (80.0, "critical"),
    (60.0, "inflated"),
    (40.0, "questionable"),
    (20.0, "noted"),
)

_BLOCKER_BAND_FLOOR = "questionable"
_HIGH_FINDINGS_BAND_FLOOR = "noted"
_HIGH_FINDINGS_COUNT = 3


class AuditBand(str, Enum):
    """Verdict class of one audit."""

    SOUND = "sound"
    NOTED = "noted"
    QUESTIONABLE = "questionable"
    INFLATED = "inflated"
    CRITICAL = "critical"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class ScoreWeights:
    """Declared weight of each dimension. Weights are policy, not measurement."""

    substance: float = 0.35
    structure_integrity: float = 0.25
    documentation_balance: float = 0.20
    import_hygiene: float = 0.20

    def __post_init__(self) -> None:
        total = 0.0
        for name in DIMENSION_NAMES:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"weight {name!r} must be a finite nonnegative number.")
            number = float(value)
            if not math.isfinite(number) or number < 0.0:
                raise ValueError(f"weight {name!r} must be a finite nonnegative number.")
            total += number
        if total <= 0.0:
            raise ValueError("weights must not sum to zero.")

    def as_mapping(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in DIMENSION_NAMES}

    def declared_for(self, names: Sequence[str]) -> dict[str, float]:
        """Return the weight of each scored dimension, refusing an unknown name."""
        mapping = self.as_mapping()
        unknown = sorted({name for name in names if name not in mapping})
        if unknown:
            raise ValueError(
                f"no declared weight for dimension(s) {unknown}; a scored dimension "
                "must never be silently unweighted."
            )
        return {name: mapping[name] for name in names}


@dataclass(frozen=True)
class DimensionValue:
    """One measured dimension, with the measurement that produced it.

    A value outside ``[0, 1]`` is clamped and recorded as clamped rather than
    rejected, because a measurement bug must be visible in the report instead of
    silently distorting a score.
    """

    name: str
    value: float
    measurement: str
    clamped: bool = field(default=False)

    def __post_init__(self) -> None:
        if self.name not in DIMENSION_NAMES:
            raise ValueError(
                f"unknown dimension {self.name!r}; expected one of {list(DIMENSION_NAMES)}."
            )
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("value must be a finite number.")
        number = float(self.value)
        if not math.isfinite(number):
            raise ValueError("value must be a finite number.")
        if not isinstance(self.measurement, str) or not self.measurement:
            raise ValueError("measurement must be a nonempty string.")
        if self.measurement != self.measurement.strip():
            raise ValueError("measurement must not carry surrounding whitespace.")
        bounded = max(0.0, min(1.0, number))
        if bounded != number:
            object.__setattr__(self, "clamped", True)
            object.__setattr__(self, "value", bounded)


@dataclass(frozen=True)
class AuditScore:
    """Deficit, band and attribution produced by one scoring pass."""

    deficit: float
    band: AuditBand
    base_deficit: float
    pattern_penalty: float
    dimensions: Mapping[str, float]
    skipped: tuple[str, ...]
    clamped: tuple[str, ...]
    attribution: Mapping[str, float]
    findings_total: int
    reason_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "deficit": self.deficit,
            "band": self.band.value,
            "base_deficit": self.base_deficit,
            "pattern_penalty": self.pattern_penalty,
            "dimensions": dict(self.dimensions),
            "skipped": list(self.skipped),
            "clamped": list(self.clamped),
            "attribution": dict(self.attribution),
            "findings_total": self.findings_total,
            "reason_code": self.reason_code,
        }


def compute_audit_score(
    dimensions: Sequence[DimensionValue],
    findings: Sequence[RuleFinding],
    weights: ScoreWeights | None = None,
    *,
    suppressed: Sequence[str] = (),
    reason_code: str | None = None,
) -> AuditScore:
    """Score one module from its measured dimensions and its pattern findings.

    ``suppressed`` names dimensions the caller's role profile decided not to
    judge. Those are excluded from the geometric mean, recorded as skipped, and
    must match a dimension that was actually measured: a misspelled suppression
    is an error, not a silent no-op.
    """
    declared = tuple(dimensions)
    if not declared:
        raise ValueError("at least one measured dimension is required.")
    if not all(isinstance(item, DimensionValue) for item in declared):
        raise TypeError("dimensions must contain DimensionValue instances.")
    names = [item.name for item in declared]
    if len(set(names)) != len(names):
        raise ValueError("a dimension must be measured at most once per audit.")

    suppressed_names = tuple(suppressed)
    unknown_suppressed = sorted(set(suppressed_names) - set(names))
    if unknown_suppressed:
        raise ValueError(
            f"suppressed dimension(s) {unknown_suppressed} were never measured."
        )
    skipped = tuple(sorted(set(suppressed_names)))
    policy = weights if weights is not None else ScoreWeights()
    if not isinstance(policy, ScoreWeights):
        raise TypeError("weights must be a ScoreWeights instance.")
    declared_weights = policy.declared_for(names)

    effective = [
        (item.name, 1.0 if item.name in skipped else item.value) for item in declared
    ]
    active = [(name, value) for name, value in effective if declared_weights[name] > 0.0]
    if not active:
        raise ValueError(
            "every scored dimension carries zero weight; the audit cannot produce a deficit."
        )
    total_weight = sum(declared_weights[name] for name, _ in active)
    log_sum = sum(
        declared_weights[name] * math.log(max(EPSILON, value)) for name, value in active
    )
    geometric = math.exp(log_sum / total_weight)
    base_deficit = 100.0 * (1.0 - geometric)

    for finding in findings:
        if not isinstance(finding, RuleFinding):
            raise TypeError("findings must contain RuleFinding instances.")
    pattern_penalty = _pattern_penalty(findings)
    raw = base_deficit + pattern_penalty
    deficit = round(min(100.0, raw), 6)

    clamped = tuple(sorted(item.name for item in declared if item.clamped))
    return AuditScore(
        deficit=deficit,
        band=_band(deficit, findings),
        base_deficit=round(base_deficit, 6),
        pattern_penalty=round(pattern_penalty, 6),
        dimensions={name: round(value, 6) for name, value in effective},
        skipped=skipped,
        clamped=clamped,
        attribution=_attribution(declared_weights, active, base_deficit, pattern_penalty),
        findings_total=len(findings),
        reason_code=reason_code,
    )


def _pattern_penalty(findings: Sequence[RuleFinding]) -> float:
    total = 0.0
    ordered = sorted(findings, key=lambda item: item.sort_key)
    for finding in ordered:
        severity = finding.severity.value
        if severity not in SEVERITY_PENALTY:
            raise ValueError(f"no penalty is declared for severity {severity!r}.")
        total += SEVERITY_PENALTY[severity]
    return min(total, PATTERN_PENALTY_CAP)


def _band(deficit: float, findings: Sequence[RuleFinding]) -> AuditBand:
    band = AuditBand.SOUND
    for threshold, name in BAND_THRESHOLDS:
        if deficit >= threshold:
            band = AuditBand(name)
            break
    blockers = sum(1 for item in findings if item.severity is RuleSeverity.BLOCKER)
    highs = sum(1 for item in findings if item.severity is RuleSeverity.HIGH)
    if blockers and band in {AuditBand.SOUND, AuditBand.NOTED}:
        band = AuditBand(_BLOCKER_BAND_FLOOR)
    elif highs >= _HIGH_FINDINGS_COUNT and band is AuditBand.SOUND:
        band = AuditBand(_HIGH_FINDINGS_BAND_FLOOR)
    return band


def _attribution(
    declared_weights: Mapping[str, float],
    active: Sequence[tuple[str, float]],
    base_deficit: float,
    pattern_penalty: float,
) -> dict[str, float]:
    losses = {
        name: -declared_weights[name] * math.log(max(EPSILON, value))
        for name, value in active
    }
    total_weight = sum(declared_weights[name] for name, _ in active)
    total_loss = sum(losses.values()) / total_weight
    deficit = base_deficit + pattern_penalty
    if deficit <= 1e-9:
        return {name: 0.0 for name in losses} | {"rule_penalty": 0.0}
    rule_share = pattern_penalty / deficit
    dimension_scale = base_deficit / deficit
    shares = {
        name: (loss / total_weight) / total_loss * dimension_scale if total_loss > 1e-9 else 0.0
        for name, loss in losses.items()
    }
    shares["rule_penalty"] = rule_share
    return {name: round(value, 6) for name, value in shares.items()}
