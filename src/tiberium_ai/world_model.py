"""Predictive World Model and JEPA-style action gate.

Evaluates action transitions in representation space rather than raw tokens
or pixels, enabling early pruning of loops, dead clicks, and anomalies before
consuming expensive LLM reasoning tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping, Sequence

from .router import is_nonnegative_number

__all__ = [
    "ActionDescriptor",
    "ActionGateVerdict",
    "GateRecommendation",
    "JEPAActionGate",
    "StateVector",
    "TransitionRecord",
]


class GateRecommendation(str, Enum):
    ADMIT = "ADMIT"                 # Action admitted for execution
    PRUNE_LOOP = "PRUNE_LOOP"       # Stagnation: predicted state has zero delta (dead click / loop)
    PRUNE_ANOMALY = "PRUNE_ANOMALY" # High energy: transition diverges from objective or hits known trap
    REQUIRE_EVIDENCE = "REQUIRE_EVIDENCE" # Uncertainty too high; requires prior verification


@dataclass(frozen=True)
class StateVector:
    """Normalized representation vector of an environment or page state."""

    features: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.features:
            raise ValueError("features tuple cannot be empty.")
        for f in self.features:
            if not isinstance(f, (int, float)) or not math.isfinite(f):
                raise ValueError("All features must be finite numbers.")

    def distance_to(self, other: StateVector) -> float:
        """Euclidean distance in representation space."""
        if len(self.features) != len(other.features):
            raise ValueError("State vectors must have identical dimensions.")
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(self.features, other.features)))

    def cosine_similarity(self, other: StateVector) -> float:
        """Cosine similarity in representation space."""
        if len(self.features) != len(other.features):
            raise ValueError("State vectors must have identical dimensions.")
        dot = sum(a * b for a, b in zip(self.features, other.features))
        norm_a = math.sqrt(sum(a ** 2 for a in self.features))
        norm_b = math.sqrt(sum(b ** 2 for b in other.features))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


@dataclass(frozen=True)
class ActionDescriptor:
    """Typed specification of an intended action."""

    name: str
    target: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    is_mutation: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Action name must be a nonempty string.")
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("Action target must be a nonempty string.")


@dataclass(frozen=True)
class ActionGateVerdict:
    """Outcome of a JEPA-style action gate check."""

    admitted: bool
    energy_score: float
    recommendation: GateRecommendation
    rationale: str


@dataclass(frozen=True)
class TransitionRecord:
    """Captured transition for building statistical baselines and training offline predictors."""

    state_before: StateVector
    action: ActionDescriptor
    state_after: StateVector
    verified_success: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)


class JEPAActionGate:
    """Evaluates whether an action should proceed based on latent state transitions.

    Invariants:
    - If a mutating action produces a predicted delta < min_state_delta, it flags PRUNE_LOOP
      (prevents paying tokens for repeated no-ops / dead clicks).
    - If distance to target state increases beyond energy_threshold, flags PRUNE_ANOMALY.
    - All observed transitions can be appended to an offline registry without modifying production routes.
    """

    def __init__(
        self,
        energy_threshold: float = 1.5,
        min_state_delta: float = 0.05,
    ) -> None:
        if not is_nonnegative_number(energy_threshold):
            raise ValueError("energy_threshold must be a finite nonnegative number.")
        if not is_nonnegative_number(min_state_delta):
            raise ValueError("min_state_delta must be a finite nonnegative number.")

        self.energy_threshold = energy_threshold
        self.min_state_delta = min_state_delta
        self._history: list[TransitionRecord] = []

    @property
    def transition_count(self) -> int:
        return len(self._history)

    def record_transition(
        self,
        before: StateVector,
        action: ActionDescriptor,
        after: StateVector,
        verified: bool,
        metadata: Mapping[str, Any] | None = None,
    ) -> TransitionRecord:
        record = TransitionRecord(
            state_before=before,
            action=action,
            state_after=after,
            verified_success=verified,
            metadata=dict(metadata or {}),
        )
        self._history.append(record)
        return record

    def evaluate(
        self,
        current_state: StateVector,
        action: ActionDescriptor,
        predicted_next_state: StateVector,
        target_state: StateVector | None = None,
    ) -> ActionGateVerdict:
        """Evaluate action feasibility and energy before execution."""
        delta = current_state.distance_to(predicted_next_state)

        # Dead click / loop detection: a mutating action should change interface state
        if action.is_mutation and delta < self.min_state_delta:
            return ActionGateVerdict(
                admitted=False,
                energy_score=delta,
                recommendation=GateRecommendation.PRUNE_LOOP,
                rationale=f"Stagnation detected: predicted delta {delta:.4f} < {self.min_state_delta} for mutation '{action.name}'.",
            )

        # If target goal state is provided, compute energy as distance to target
        if target_state is not None:
            dist_current = current_state.distance_to(target_state)
            dist_predicted = predicted_next_state.distance_to(target_state)
            energy = dist_predicted

            # If action moves significantly away from target state
            if dist_predicted > dist_current + self.energy_threshold:
                return ActionGateVerdict(
                    admitted=False,
                    energy_score=energy,
                    recommendation=GateRecommendation.PRUNE_ANOMALY,
                    rationale=f"Energy barrier exceeded: predicted distance {dist_predicted:.2f} diverges from target ({dist_current:.2f}).",
                )

            return ActionGateVerdict(
                admitted=True,
                energy_score=energy,
                recommendation=GateRecommendation.ADMIT,
                rationale=f"Action admitted: moves state closer to target ({dist_predicted:.2f} <= {dist_current:.2f}).",
            )

        # Without explicit target state, admission depends on non-stagnation
        return ActionGateVerdict(
            admitted=True,
            energy_score=delta,
            recommendation=GateRecommendation.ADMIT,
            rationale=f"Action admitted with valid predicted state delta ({delta:.4f}).",
        )
