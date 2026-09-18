from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

@dataclass(frozen=True)
class Task:
    task_id: str
    kind: str
    inputs: Mapping[str, Any]
    risk_class: str = "low"
    evidence_level: str = "normal"
    locality: str = "any"

@dataclass(frozen=True)
class CandidateRoute:
    """Caller-supplied estimates, not measurements or verified guarantees.

    All estimated_cost values in one proposal must use the same unit and
    estimation basis. None means unknown; zero means an explicit zero estimate.
    estimated_latency_ms is descriptive only in the current shadow router.
    """

    route_id: str
    capability_ids: Sequence[str]
    estimated_cost: float | None = None
    estimated_latency_ms: float | None = None
    confidence: float | None = None
    known_failure_modes: Sequence[str] = field(default_factory=tuple)

@dataclass(frozen=True)
class Decision:
    task_id: str
    selected_route_id: str | None
    mode: str = "shadow"
    rationale: str = ""
    abstained: bool = False

_VERIFICATION_FIELDS = frozenset(
    {"verifier_id", "verifier_version", "verdict", "input_hash", "detail_code"}
)


def validate_verification_record(record: object) -> None:
    """Validate one verifier-attribution block."""
    if not isinstance(record, dict) or set(record) != _VERIFICATION_FIELDS:
        raise ValueError(
            f"verification must contain exactly {sorted(_VERIFICATION_FIELDS)}."
        )
    for name in ("verifier_id", "verifier_version"):
        value = record[name]
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"verification.{name} must be a nonempty, trimmed string.")
    verdict = record["verdict"]
    if verdict is not None and not isinstance(verdict, bool):
        raise ValueError("verification.verdict must be a boolean or null.")
    input_hash = record["input_hash"]
    if (
        not isinstance(input_hash, str)
        or len(input_hash) != 64
        or any(character not in "0123456789abcdef" for character in input_hash)
    ):
        raise ValueError(
            "verification.input_hash must be 64 lowercase hexadecimal characters."
        )
    detail_code = record["detail_code"]
    if detail_code is not None and (
        not isinstance(detail_code, str)
        or not detail_code
        or detail_code != detail_code.strip()
    ):
        raise ValueError(
            "verification.detail_code must be null or a nonempty, trimmed string."
        )
    if verdict is None and detail_code is None:
        raise ValueError("verification.detail_code must explain an abstention.")


@dataclass(frozen=True)
class Verification:
    """Outcome of one named and versioned verifier run on one input.

    `verdict` is True (accepted), False (rejected) or None (abstained, for
    example when no verifier is registered under that identity).
    """

    verifier_id: str
    verifier_version: str
    verdict: bool | None
    input_hash: str
    detail_code: str | None = None

    def __post_init__(self) -> None:
        validate_verification_record(self.to_record())

    def to_record(self) -> dict[str, Any]:
        return {
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "verdict": self.verdict,
            "input_hash": self.input_hash,
            "detail_code": self.detail_code,
        }


@dataclass(frozen=True)
class Evidence:
    task_id: str
    route_id: str
    verifier_ok: bool
    measured_latency_ms: float | None = None
    measured_cost: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    verification: Verification | None = None
