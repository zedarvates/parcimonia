"""Discrete pattern checks over an already-scanned module.

A rule is a small, named, deterministic predicate. It declares the axis and the
severity of what it finds, the roles it is willing to judge, and it returns
findings that carry a stable machine-readable ``detail_code`` plus a
human-readable message. Nothing here reads a file, imports the module under
analysis or calls a model.

The registry is versioned by fingerprint: rule ids, axes, severities and role
applicability are hashed into the audit policy version, so a rule edit cannot
silently reuse a verdict computed under the previous rule set. A rule that
cannot be checked raises; a rule that finds nothing returns no finding.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from .source_role import SourceRole
from .source_scan import SourceScan

__all__ = [
    "MACHINE_RULES",
    "GOD_FUNCTION_DECISION_POINTS",
    "Rule",
    "RuleAxis",
    "RuleFinding",
    "RuleRegistry",
    "RuleSeverity",
    "builtin_rule_registry",
]

#: Upper bound on findings of one rule in one file. The cap bounds the penalty a
#: single repeated defect can add and keeps a report readable; the count is
#: still reported through the score attribution.
FINDING_CAP = 5

RULE_REGISTRY_SCHEMA = 1

#: Decision points allowed in one function before it is reported as oversized.
#: The audit dimensions read the same constant, so a rule and a dimension never
#: disagree about where the bound is.
#:
#: This is a declared default, not a calibrated value. A decision-point count
#: measures length, and a long flat sequence of independent checks is not the
#: same defect as deeply nested logic, so the bound is deliberately loose and the
#: authored corpus records both a function that must fire and a long flat one
#: that must not. A measured calibration is what could tighten it.
GOD_FUNCTION_DECISION_POINTS = 25


class RuleAxis(str, Enum):
    """What a rule is about, used to group findings in a report."""

    STRUCTURE = "structure"
    PLACEHOLDER = "placeholder"
    HYGIENE = "hygiene"
    CLAIM = "claim"


class RuleSeverity(str, Enum):
    """How much a single finding of this rule weighs in the deficit."""

    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class RuleFinding:
    """One located pattern hit."""

    rule_id: str
    axis: RuleAxis
    severity: RuleSeverity
    line: int
    column: int
    detail_code: str
    message: str

    def __post_init__(self) -> None:
        for name in ("rule_id", "detail_code", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be a nonempty, trimmed string.")
        if not isinstance(self.axis, RuleAxis):
            raise TypeError("axis must be a RuleAxis.")
        if not isinstance(self.severity, RuleSeverity):
            raise TypeError("severity must be a RuleSeverity.")
        for name in ("line", "column"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (self.line, self.column, self.rule_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "axis": self.axis.value,
            "severity": self.severity.value,
            "line": self.line,
            "column": self.column,
            "detail_code": self.detail_code,
            "message": self.message,
        }


class Rule(ABC):
    """One named deterministic pattern check."""

    rule_id: str = ""
    axis: RuleAxis = RuleAxis.STRUCTURE
    severity: RuleSeverity = RuleSeverity.MEDIUM
    description: str = ""
    applies_to: frozenset[SourceRole] = frozenset(SourceRole)

    def is_applicable(self, role: SourceRole) -> bool:
        return role in self.applies_to

    def finding(
        self,
        *,
        line: int,
        column: int = 0,
        detail_code: str,
        message: str,
        severity_override: RuleSeverity | None = None,
    ) -> RuleFinding:
        """Build a finding carrying this rule's identity and severity.

        ``severity_override`` exists for the cases where one rule has a benign and
        a dangerous form: a bare handler is not the same defect as a typed handler
        with an empty body, and the rule that knows the difference should say so
        rather than push that judgement into the scorer.
        """
        return RuleFinding(
            rule_id=self.rule_id,
            axis=self.axis,
            severity=severity_override if severity_override is not None else self.severity,
            line=line,
            column=column,
            detail_code=detail_code,
            message=message,
        )

    @abstractmethod
    def check(self, scan: SourceScan) -> tuple[RuleFinding, ...]:
        """Return this rule's findings for one module, already capped and sorted."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(id={self.rule_id!r})"


def _cap(findings: list[RuleFinding]) -> tuple[RuleFinding, ...]:
    findings.sort(key=lambda item: item.sort_key)
    return tuple(findings[:FINDING_CAP])


_PLACEHOLDER_MARKERS = (
    "todo",
    "fixme",
    "placeholder",
    "for now",
    "not implemented",
    "stub",
    "temporary workaround",
)

#: Word boundaries matter here: without them the exception class name
#: ``NotImplementedError`` contains the two-word deferred-work marker, which is
#: exactly the kind of false positive a role classifier must remove, not create.
_PLACEHOLDER_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(marker) for marker in _PLACEHOLDER_MARKERS) + r")\b",
    re.IGNORECASE,
)


class PlaceholderMarkerRule(Rule):
    """Comment that announces unfinished work.

    Only comments are read, not docstrings. A docstring describes behaviour, and
    sentences such as "two-stage scoring is not implemented" are accurate prose
    about a deliberate limitation, not deferred work. Restricting the rule to
    comments removes that whole class of false positive; extending it back to
    docstrings is a calibration decision, not a default.
    """

    rule_id = "rule.placeholder-marker"
    axis = RuleAxis.PLACEHOLDER
    severity = RuleSeverity.MEDIUM
    description = "A comment or docstring marks behaviour as deferred or provisional."
    applies_to = frozenset({SourceRole.MODULE, SourceRole.PACKAGE_INIT, SourceRole.INTERFACE})

    def check(self, scan: SourceScan) -> tuple[RuleFinding, ...]:
        findings = []
        for line, text in scan.comments:
            match = _PLACEHOLDER_PATTERN.search(text)
            if match is None:
                continue
            marker = match.group(0).lower()
            findings.append(
                self.finding(
                    line=line,
                    column=match.start(),
                    detail_code=f"marker.{marker.split()[0]}",
                    message=f"deferred-work marker {marker!r} in comment",
                )
            )
        return _cap(findings)


class SilentExceptRule(Rule):
    """Exception handler that swallows a failure without reporting it."""

    rule_id = "rule.silent-except"
    axis = RuleAxis.STRUCTURE
    severity = RuleSeverity.HIGH
    description = "A bare handler, or one whose whole body is pass/ellipsis."
    applies_to = frozenset(
        {SourceRole.MODULE, SourceRole.PACKAGE_INIT, SourceRole.INTERFACE, SourceRole.TEST}
    )

    def check(self, scan: SourceScan) -> tuple[RuleFinding, ...]:
        findings = []
        for node in ast.walk(scan.tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                findings.append(
                    self.finding(
                        line=node.lineno,
                        column=node.col_offset,
                        detail_code="except.bare",
                        message="bare except catches every exception, including exit signals",
                        severity_override=RuleSeverity.BLOCKER,
                    )
                )
            if _swallows(node.body):
                findings.append(
                    self.finding(
                        line=node.lineno,
                        column=node.col_offset,
                        detail_code="except.silent",
                        message="handler body is only pass or a bare string, so the failure leaves no trace",
                    )
                )
        return _cap(findings)


class DebugEmitRule(Rule):
    """Leftover interactive debugging output in an authored module."""

    rule_id = "rule.debug-emit"
    axis = RuleAxis.HYGIENE
    severity = RuleSeverity.LOW
    description = "print(), breakpoint() or set_trace() left in a module body."
    applies_to = frozenset({SourceRole.MODULE, SourceRole.PACKAGE_INIT})

    def check(self, scan: SourceScan) -> tuple[RuleFinding, ...]:
        findings = []
        for node in ast.walk(scan.tree):
            if not isinstance(node, ast.Call):
                continue
            target = _call_name(node.func)
            if target in {"print", "breakpoint"}:
                findings.append(
                    self.finding(
                        line=node.lineno,
                        column=node.col_offset,
                        detail_code=f"emit.{target}",
                        message=f"{target}() call in authored code",
                    )
                )
            elif target.endswith(".set_trace"):
                findings.append(
                    self.finding(
                        line=node.lineno,
                        column=node.col_offset,
                        detail_code="emit.set_trace",
                        message="debugger breakpoint left in authored code",
                    )
                )
        return _cap(findings)


_CLAIM_PHRASES = (
    "production-ready",
    "production ready",
    "battle-tested",
    "blazing fast",
    "enterprise-grade",
    "world-class",
    "state-of-the-art",
    "revolutionary",
    "flawless",
    "unmatched",
    "fully tested",
    "guaranteed",
    "effortless",
    "seamless",
    "100%",
)

_CLAIM_PATTERN = re.compile(
    "|".join(re.escape(phrase) for phrase in _CLAIM_PHRASES), re.IGNORECASE
)


class InflatedClaimRule(Rule):
    """Comment or docstring asserting a quality the code does not demonstrate.

    This is a small, explicit lexicon, not a judgement about meaning. It is
    expected to be tuned against labelled examples before any threshold built on
    it is trusted; until then it is a hint, and it is reported as one.
    """

    rule_id = "rule.inflated-claim"
    axis = RuleAxis.CLAIM
    severity = RuleSeverity.MEDIUM
    description = "Marketing register in a comment or docstring."
    applies_to = frozenset(
        {
            SourceRole.MODULE,
            SourceRole.PACKAGE_INIT,
            SourceRole.RE_EXPORT,
            SourceRole.INTERFACE,
        }
    )

    def check(self, scan: SourceScan) -> tuple[RuleFinding, ...]:
        findings = []
        for line, text in (*scan.comments, *scan.docstrings):
            match = _CLAIM_PATTERN.search(text)
            if match is None:
                continue
            phrase = match.group(0).lower()
            findings.append(
                self.finding(
                    line=line,
                    column=match.start(),
                    detail_code=f"claim.{phrase.replace(' ', '-')}",
                    message=f"unverified quality claim {phrase!r} in comment or docstring",
                )
            )
        return _cap(findings)


class GodFunctionRule(Rule):
    """A single function holding more decisions than one unit should."""

    rule_id = "rule.god-function"
    axis = RuleAxis.STRUCTURE
    severity = RuleSeverity.MEDIUM
    description = "A function concentrates decisions that belong in separate units."
    applies_to = frozenset({SourceRole.MODULE, SourceRole.PACKAGE_INIT})

    def check(self, scan: SourceScan) -> tuple[RuleFinding, ...]:
        findings = []
        for function in scan.functions:
            if function.decision_points <= GOD_FUNCTION_DECISION_POINTS:
                continue
            findings.append(
                self.finding(
                    line=function.line,
                    detail_code="structure.god-function",
                    message=(
                        f"{function.qualname} holds {function.decision_points} decision "
                        f"points, above the bound of {GOD_FUNCTION_DECISION_POINTS}"
                    ),
                )
            )
        return _cap(findings)


def _swallows(body: list[ast.stmt]) -> bool:
    """Return whether a handler body is only ``pass`` or a bare string.

    ``continue``, ``break`` and ``return`` are deliberate control flow the author
    chose, not a swallowed failure, so a typed handler using them is left alone;
    an untyped handler is still reported by the bare-except branch.
    """
    if not body:
        return True
    return all(
        isinstance(statement, ast.Pass)
        or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
        )
        for statement in body
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


class RuleRegistry:
    """Validated, versioned set of pattern rules."""

    def __init__(self, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
        self._rules: dict[str, Rule] = {}
        self._disabled: set[str] = set()
        for rule in rules:
            self.register(rule)

    def register(self, rule: Rule) -> None:
        if not isinstance(rule, Rule):
            raise TypeError("rule must be a Rule instance.")
        identifier = rule.rule_id
        if not isinstance(identifier, str) or not identifier or identifier != identifier.strip():
            raise ValueError("rule_id must be a nonempty, trimmed string.")
        if identifier in self._rules:
            raise ValueError(f"rule {identifier!r} is already registered.")
        if not isinstance(rule.applies_to, frozenset) or not rule.applies_to:
            raise ValueError(f"rule {identifier!r} must apply to at least one role.")
        self._rules[identifier] = rule

    def enable(self, rule_id: str) -> None:
        self._require(rule_id)
        self._disabled.discard(rule_id)

    def disable(self, rule_id: str) -> None:
        self._require(rule_id)
        self._disabled.add(rule_id)

    def is_enabled(self, rule_id: str) -> bool:
        self._require(rule_id)
        return rule_id not in self._disabled

    def get(self, rule_id: str) -> Rule:
        return self._rules[self._require(rule_id)]

    def rules(self) -> tuple[Rule, ...]:
        """Return the enabled rules in a stable order."""
        return tuple(
            rule
            for identifier, rule in sorted(self._rules.items())
            if identifier not in self._disabled
        )

    def run(self, scan: SourceScan, role: SourceRole) -> tuple[RuleFinding, ...]:
        """Run every applicable enabled rule and return findings in file order."""
        findings: list[RuleFinding] = []
        for rule in self.rules():
            if not rule.is_applicable(role):
                continue
            findings.extend(rule.check(scan))
        findings.sort(key=lambda item: item.sort_key)
        return tuple(findings)

    def fingerprint(self) -> str:
        """Hash what actually runs, so a rule edit changes the policy version."""
        payload = {
            "schema": RULE_REGISTRY_SCHEMA,
            "findings_cap": FINDING_CAP,
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "axis": rule.axis.value,
                    "severity": rule.severity.value,
                    "applies_to": sorted(role.value for role in rule.applies_to),
                }
                for rule in self.rules()
            ],
        }
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _require(self, rule_id: str) -> str:
        if not isinstance(rule_id, str) or not rule_id or rule_id != rule_id.strip():
            raise ValueError("rule_id must be a nonempty, trimmed string.")
        if rule_id not in self._rules:
            raise ValueError(f"unknown rule_id {rule_id!r}.")
        return rule_id

    def __len__(self) -> int:
        return len(self._rules) - len(self._disabled)


MACHINE_RULES: tuple[Rule, ...] = (
    PlaceholderMarkerRule(),
    SilentExceptRule(),
    DebugEmitRule(),
    InflatedClaimRule(),
    GodFunctionRule(),
)


def builtin_rule_registry() -> RuleRegistry:
    """Return a fresh registry holding the shipped rules."""
    return RuleRegistry(list(MACHINE_RULES))
