"""The static-audit route: a System-1 capability expressed as a Parcimonia route.

An audit answers a question a general model would otherwise be asked: does this
file declare more than it implements? The whole mechanism is local, offline and
deterministic, so it is the cheapest candidate route Parcimonia can offer, and
the router may select it while the model-backed route stays the baseline.

This module only assembles the parts. It chooses no route, executes nothing and
costs nothing; it produces a verdict, the evidence for it, a manifest entry the
registry can load, and a deterministic verifier that recomputes the verdict from
the source instead of trusting the caller's claim.

Two invariants are enforced here because they are what makes reuse safe:

* the policy version must carry the fingerprint of the rule set that runs, so a
  verdict computed under different rules can never be attributed to this one
* a verdict that could not be determined is an abstention: it is reported as
  ``undetermined``, is never offered for reuse, and never verifies as accepted
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .audit_score import (
    DIMENSION_NAMES,
    AuditBand,
    DimensionValue,
    ScoreWeights,
    compute_audit_score,
)
from .audit_store import AuditRecord, SqliteAuditStore
from .pattern_rules import (
    GOD_FUNCTION_DECISION_POINTS,
    RuleFinding,
    RuleRegistry,
    builtin_rule_registry,
)
from .source_role import SUPPRESS_ALL, RoleProfile, SourceRole, classify_source_role
from .source_scan import SourceScanError, scan_source
from .verification import VerifierRegistry, hash_input

__all__ = [
    "AUDIT_CAPABILITY",
    "AUDIT_TOOL_VERSION",
    "AUDIT_VERIFIER_ID",
    "AUDIT_VERIFIER_VERSION",
    "COMPLEXITY_THRESHOLD",
    "AuditOutcome",
    "AuditRequest",
    "audit_policy_version",
    "audit_route_entry",
    "audit_source",
    "measure_dimensions",
    "recompute_verifier",
    "register_audit_verifiers",
]

#: Capability this route provides. A consumer asks for a structural audit; it
#: never asks for "the slop detector".
AUDIT_CAPABILITY = "audit.static.structure@1"

AUDIT_VERIFIER_ID = "audit.recompute"
AUDIT_VERIFIER_VERSION = "1"

#: Version of the measurement rules, independent of the rule registry.
AUDIT_TOOL_VERSION = "1"

#: Decision points allowed in one function. The rule registry publishes the same
#: bound, so the ratio dimension and the discrete rule never disagree about it.
COMPLEXITY_THRESHOLD = GOD_FUNCTION_DECISION_POINTS

_REASON_UNPARSABLE = "source_unparsable"
_REASON_SUPPRESSED = "role_suppresses_all_checks"


@dataclass(frozen=True)
class AuditRequest:
    """One module to audit, already read by the caller."""

    task_id: str
    path: str
    source: str

    def __post_init__(self) -> None:
        for name in ("task_id", "path"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be a nonempty, trimmed string.")
        if not isinstance(self.source, str):
            raise TypeError("source must be a string.")


@dataclass(frozen=True)
class AuditOutcome:
    """Verdict of one audit, with the evidence needed to challenge it."""

    task_id: str
    path: str
    content_hash: str
    policy_version: str
    role: str
    role_reason: str
    band: str
    deficit: float | None
    dimensions: Mapping[str, float]
    skipped: tuple[str, ...]
    rule_counts: Mapping[str, int]
    attribution: Mapping[str, float]
    findings_total: int
    findings: tuple[RuleFinding, ...] = ()
    reused: bool = False
    reason_code: str | None = None

    @property
    def determined(self) -> bool:
        return self.band != AuditBand.UNDETERMINED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "path": self.path,
            "content_hash": self.content_hash,
            "policy_version": self.policy_version,
            "role": self.role,
            "role_reason": self.role_reason,
            "band": self.band,
            "deficit": self.deficit,
            "dimensions": dict(self.dimensions),
            "skipped": list(self.skipped),
            "rule_counts": dict(self.rule_counts),
            "attribution": dict(self.attribution),
            "findings_total": self.findings_total,
            "reused": self.reused,
            "reason_code": self.reason_code,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_record(
        self, *, recorded_at: str, project_id: str, data_origin: str = "measured"
    ) -> AuditRecord:
        """Project the outcome onto the fields the local store keeps."""
        return AuditRecord(
            recorded_at=recorded_at,
            project_id=project_id,
            policy_version=self.policy_version,
            content_hash=self.content_hash,
            role=self.role,
            role_reason=self.role_reason,
            band=self.band,
            deficit=self.deficit,
            dimensions=dict(self.dimensions),
            skipped=self.skipped,
            rule_counts=dict(self.rule_counts),
            attribution=dict(self.attribution),
            findings_total=self.findings_total,
            data_origin=data_origin,
        )


def audit_policy_version(base: str, registry: RuleRegistry | None = None) -> str:
    """Return a policy version that pins the rule set that actually runs."""
    if not isinstance(base, str) or not base or base != base.strip():
        raise ValueError("base must be a nonempty, trimmed string.")
    active = registry if registry is not None else builtin_rule_registry()
    if not isinstance(active, RuleRegistry):
        raise TypeError("registry must be a RuleRegistry instance.")
    return f"{base}+rules:{active.fingerprint()}"


def audit_source(
    request: AuditRequest,
    *,
    policy_version: str,
    registry: RuleRegistry | None = None,
    weights: ScoreWeights | None = None,
    store: SqliteAuditStore | None = None,
    recorded_at: str | None = None,
    project_id: str | None = None,
    data_origin: str = "measured",
) -> AuditOutcome:
    """Audit one module, optionally reusing and recording a stored verdict.

    When a store is supplied, ``recorded_at`` and ``project_id`` are required: it
    is better to refuse the call than to record an audit without provenance.
    """
    if not isinstance(request, AuditRequest):
        raise TypeError("request must be an AuditRequest instance.")
    active = registry if registry is not None else builtin_rule_registry()
    if not isinstance(active, RuleRegistry):
        raise TypeError("registry must be a RuleRegistry instance.")
    _check_policy_version(policy_version, active)
    if store is not None:
        if not isinstance(store, SqliteAuditStore):
            raise TypeError("store must be a SqliteAuditStore instance.")
        for name, value in (("recorded_at", recorded_at), ("project_id", project_id)):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(
                    f"{name} is required when a store is given: an audit must carry provenance."
                )

    content_hash = hash_input({"path": request.path, "source": request.source})
    if store is not None:
        cached = store.reuse(content_hash, policy_version)
        if cached is not None:
            return AuditOutcome(
                task_id=request.task_id,
                path=request.path,
                content_hash=cached.content_hash,
                policy_version=cached.policy_version,
                role=cached.role,
                role_reason=cached.role_reason,
                band=cached.band,
                deficit=cached.deficit,
                dimensions=dict(cached.dimensions),
                skipped=tuple(cached.skipped),
                rule_counts=dict(cached.rule_counts),
                attribution=dict(cached.attribution),
                findings_total=cached.findings_total,
                reused=True,
            )

    outcome = _analyse(request, content_hash, policy_version, active, weights)
    if store is not None:
        store.record(
            outcome.to_record(
                recorded_at=recorded_at or "", project_id=project_id or "", data_origin=data_origin
            )
        )
    return outcome


def _analyse(
    request: AuditRequest,
    content_hash: str,
    policy_version: str,
    registry: RuleRegistry,
    weights: ScoreWeights | None,
) -> AuditOutcome:
    try:
        scan = scan_source(request.path, request.source)
    except SourceScanError:
        return _undetermined(request, content_hash, policy_version, _REASON_UNPARSABLE)

    profile = classify_source_role(scan)
    _check_suppressions(profile.suppressions)
    if profile.suppresses_everything:
        return _undetermined(
            request,
            content_hash,
            policy_version,
            _REASON_SUPPRESSED,
            role=profile.role.value,
            role_reason=profile.reason_code,
        )

    findings = registry.run(scan, profile.role)
    dimensions = measure_dimensions(scan, profile)
    score = compute_audit_score(
        dimensions,
        findings,
        weights,
        suppressed=tuple(name for name in profile.suppressions if name in DIMENSION_NAMES),
    )
    return AuditOutcome(
        task_id=request.task_id,
        path=request.path,
        content_hash=content_hash,
        policy_version=policy_version,
        role=profile.role.value,
        role_reason=profile.reason_code,
        band=score.band.value,
        deficit=score.deficit,
        dimensions=dict(score.dimensions),
        skipped=score.skipped,
        rule_counts=dict(Counter(finding.rule_id for finding in findings)),
        attribution=dict(score.attribution),
        findings_total=score.findings_total,
        findings=findings,
    )


def _undetermined(
    request: AuditRequest,
    content_hash: str,
    policy_version: str,
    reason_code: str,
    *,
    role: str = SourceRole.MODULE.value,
    role_reason: str = _REASON_UNPARSABLE,
) -> AuditOutcome:
    """Report a file the audit refused to judge, instead of scoring it clean."""
    return AuditOutcome(
        task_id=request.task_id,
        path=request.path,
        content_hash=content_hash,
        policy_version=policy_version,
        role=role,
        role_reason=role_reason,
        band=AuditBand.UNDETERMINED.value,
        deficit=None,
        dimensions={},
        skipped=(),
        rule_counts={},
        attribution={},
        findings_total=0,
        reason_code=reason_code,
    )


def measure_dimensions(scan: Any, profile: RoleProfile) -> tuple[DimensionValue, ...]:
    """Measure the four ratio dimensions of one scanned module.

    Every dimension is measured even when the role suppresses it: the value is
    then excluded from the mean by the scorer, which keeps "measured but not
    judged" distinguishable from "not measured at all".
    """
    if not isinstance(profile, RoleProfile):
        raise TypeError("profile must be a RoleProfile instance.")
    function_count = len(scan.functions)
    filled = scan.filled_functions
    excess = sum(
        max(0, function.decision_points - COMPLEXITY_THRESHOLD)
        for function in scan.functions
    )
    import_count = len(scan.imports)
    used_imports = len(scan.used_imports)
    prose_lines = scan.comment_lines + scan.docstring_lines
    prose_denominator = scan.code_lines + prose_lines

    return (
        DimensionValue(
            "substance",
            1.0 if function_count == 0 else filled / function_count,
            "no function body to judge"
            if function_count == 0
            else f"{filled}/{function_count} function bodies do more than declare themselves",
        ),
        DimensionValue(
            "structure_integrity",
            1.0 if excess == 0 else 1.0 / (1.0 + excess / (COMPLEXITY_THRESHOLD * function_count)),
            "no function body to judge"
            if function_count == 0
            else f"{excess} decision point(s) beyond the bound of "
            f"{COMPLEXITY_THRESHOLD} across {function_count} function(s)",
        ),
        DimensionValue(
            "documentation_balance",
            1.0 if prose_denominator == 0 else scan.code_lines / prose_denominator,
            f"{scan.code_lines} code line(s) against {scan.comment_lines} comment and "
            f"{scan.docstring_lines} docstring line(s)",
        ),
        DimensionValue(
            "import_hygiene",
            1.0 if import_count == 0 else used_imports / import_count,
            "no import to judge"
            if import_count == 0
            else f"{used_imports}/{import_count} imported names are consumed or re-exported",
        ),
    )


def recompute_verifier(payload: Any) -> bool:
    """Accept a claimed audit verdict only if recomputation reproduces it.

    A malformed payload raises, which the verifier registry reports as an
    abstention. A well-formed payload whose claim does not match, or whose
    source turns out not to be auditable, is rejected.
    """
    if not isinstance(payload, Mapping) or set(payload) != {
        "source",
        "path",
        "policy_version",
        "claimed",
    }:
        raise ValueError(
            "payload must contain exactly source, path, policy_version and claimed."
        )
    claimed = payload["claimed"]
    if not isinstance(claimed, Mapping) or set(claimed) != {"band", "deficit", "content_hash"}:
        raise ValueError("claimed must contain exactly band, deficit and content_hash.")
    outcome = audit_source(
        AuditRequest("verify", str(payload["path"]), str(payload["source"])),
        policy_version=str(payload["policy_version"]),
    )
    if not outcome.determined:
        return False
    return (
        outcome.content_hash == claimed["content_hash"]
        and outcome.band == claimed["band"]
        and outcome.deficit == claimed["deficit"]
    )


def register_audit_verifiers(registry: VerifierRegistry) -> None:
    """Register the deterministic audit verifier under its stable identity."""
    if not isinstance(registry, VerifierRegistry):
        raise TypeError("registry must be a VerifierRegistry instance.")
    registry.register(AUDIT_VERIFIER_ID, AUDIT_VERIFIER_VERSION, recompute_verifier)


def audit_route_entry(
    *,
    route_id: str = "route.audit.static",
    estimated_cost: float | None,
    estimated_latency_ms: float | None = None,
    confidence: float | None = None,
    risk_classes: Sequence[str] = ("low",),
    evidence_levels: Sequence[str] = ("normal",),
    localities: Sequence[str] = ("any", "local"),
    verifier_id: str = AUDIT_VERIFIER_ID,
    verifier_version: str = AUDIT_VERIFIER_VERSION,
) -> dict[str, Any]:
    """Build the manifest entry for this route, without inventing its estimates.

    ``estimated_cost`` has no default on purpose: a route's cost is a measurement
    or a declared estimate, never a guess made here. The same holds for
    ``confidence``, which stays ``None`` until it has been calibrated.
    """
    return {
        "route_id": route_id,
        "capability_ids": [AUDIT_CAPABILITY],
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


def _check_policy_version(policy_version: str, registry: RuleRegistry) -> None:
    if (
        not isinstance(policy_version, str)
        or not policy_version
        or policy_version != policy_version.strip()
    ):
        raise ValueError("policy_version must be a nonempty, trimmed string.")
    expected = f"+rules:{registry.fingerprint()}"
    if not policy_version.endswith(expected):
        raise ValueError(
            "policy_version does not carry the fingerprint of the rule set that would "
            "run: a verdict cannot be attributed to rules that did not produce it."
        )


def _check_suppressions(suppressions: Sequence[str]) -> None:
    """Refuse a suppression name that matches no dimension and no wildcard.

    A misspelled suppression would otherwise turn a declared exemption into a
    silent no-op, and the file would keep a check its role meant to drop.
    """
    allowed = set(DIMENSION_NAMES) | {SUPPRESS_ALL}
    unknown = sorted({name for name in suppressions if name not in allowed})
    if unknown:
        raise ValueError(
            f"suppression(s) {unknown} match no dimension and no wildcard; a declared "
            "exemption must name the check it removes."
        )
