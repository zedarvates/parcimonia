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

@dataclass(frozen=True)
class Evidence:
    task_id: str
    route_id: str
    verifier_ok: bool
    measured_latency_ms: float | None = None
    measured_cost: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
