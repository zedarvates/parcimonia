"""Continuation decision arbiter for supervisory loops (Astral Resonance Director).

Combines remaining quota metrics, task difficulty, effector requirements (e.g. WebBrain),
and loop/stall indicators to decide whether and how an agent conversation should "continue".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import Task
from .router import is_nonnegative_number

__all__ = [
    "ContinuationAction",
    "ContinuationArbiter",
    "ContinuationVerdict",
    "QuotaMetrics",
    "RouteKind",
    "TaskDifficulty",
    "TimeBudget",
    "LocalCapacity",
]


class TaskDifficulty(str, Enum):
    DETERMINISTIC = "deterministic"
    COMPACT = "compact"
    REASONING = "reasoning"


class RouteKind(str, Enum):
    RULE = "rule"
    LOCAL_SMALL = "local_small"
    WEBBRAIN_MCP = "webbrain_mcp"
    FRONTIER = "frontier"
    NONE = "none"


class ContinuationAction(str, Enum):
    CONTINUE = "CONTINUE"
    FREEZE_QUOTA = "FREEZE_QUOTA"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"
    ESCALATE_ROUTE = "ESCALATE_ROUTE"


@dataclass(frozen=True)
class QuotaMetrics:
    """Snapshot of account/rate-limit quotas for an active window."""

    remaining_percent: float
    window_duration_mins: int
    resets_in_seconds: float | None = None
    tokens_remaining: int | None = None

    def __post_init__(self) -> None:
        if not is_nonnegative_number(self.remaining_percent) or self.remaining_percent > 100.0:
            raise ValueError("remaining_percent must be a finite number in [0.0, 100.0].")
        if type(self.window_duration_mins) is not int or self.window_duration_mins <= 0:
            raise ValueError("window_duration_mins must be a positive integer.")
        if self.resets_in_seconds is not None and not is_nonnegative_number(self.resets_in_seconds):
            raise ValueError("resets_in_seconds must be null or a finite nonnegative number.")
        if self.tokens_remaining is not None and (
            type(self.tokens_remaining) is not int or self.tokens_remaining < 0
        ):
            raise ValueError("tokens_remaining must be null or a nonnegative integer.")


@dataclass(frozen=True)
class TimeBudget:
    """Wall-clock remaining for one continuation step.

    Interactive windows refuse long frontier or browser work; a zero remainder
    still allows deterministic local rules because they cost no tokens.
    """

    remaining_seconds: float
    interactive: bool = False

    def __post_init__(self) -> None:
        if not is_nonnegative_number(self.remaining_seconds):
            raise ValueError("remaining_seconds must be a finite nonnegative number.")


@dataclass(frozen=True)
class LocalCapacity:
    """Local GPU/process budget for one continuation step.

    Missing VRAM is unknown, not zero. Zero concurrent slots block local models
    and MCP, not deterministic rules or frontier cloud routes.
    """

    vram_free_mb: float | None = None
    concurrent_slots: int = 1
    min_vram_for_local_mb: float = 256.0

    def __post_init__(self) -> None:
        if self.vram_free_mb is not None and not is_nonnegative_number(self.vram_free_mb):
            raise ValueError("vram_free_mb must be null or a finite nonnegative number.")
        if type(self.concurrent_slots) is not int or self.concurrent_slots < 0:
            raise ValueError("concurrent_slots must be a nonnegative integer.")
        if not is_nonnegative_number(self.min_vram_for_local_mb):
            raise ValueError("min_vram_for_local_mb must be a finite nonnegative number.")

    def can_start_local(self) -> bool:
        if self.concurrent_slots <= 0:
            return False
        if self.vram_free_mb is not None and self.vram_free_mb < self.min_vram_for_local_mb:
            return False
        return True


@dataclass(frozen=True)
class ContinuationVerdict:
    """Outcome of a continuation arbitration pass."""

    action: ContinuationAction
    target_route: RouteKind
    reason: str
    max_step_tokens: int | None = None


class ContinuationArbiter:
    """Deterministic arbiter deciding if and how an agent thread should continue.

    Invariants:
    - Never continues on FRONTIER when quota is critical (< critical_quota_percent).
    - If difficulty is DETERMINISTIC, always assigns RULE (0 token cost) regardless of quota.
    - If task requires browser interaction (e.g. WebBrain authenticated session), assigns WEBBRAIN_MCP.
    - If stalls >= max_consecutive_stalls, stops and requires human intervention (anti-loop safeguard).
    """

    def __init__(
        self,
        critical_quota_percent: float = 15.0,
        moderate_quota_percent: float = 40.0,
        max_consecutive_stalls: int = 2,
    ) -> None:
        if not is_nonnegative_number(critical_quota_percent) or critical_quota_percent > 100.0:
            raise ValueError("critical_quota_percent must be in [0, 100].")
        if not is_nonnegative_number(moderate_quota_percent) or moderate_quota_percent > 100.0:
            raise ValueError("moderate_quota_percent must be in [0, 100].")
        if critical_quota_percent > moderate_quota_percent:
            raise ValueError("critical_quota_percent cannot exceed moderate_quota_percent.")
        if type(max_consecutive_stalls) is not int or max_consecutive_stalls < 1:
            raise ValueError("max_consecutive_stalls must be a positive integer.")

        self.critical_quota_percent = critical_quota_percent
        self.moderate_quota_percent = moderate_quota_percent
        self.max_consecutive_stalls = max_consecutive_stalls

    def evaluate(
        self,
        task: Task,
        quota: QuotaMetrics,
        difficulty: TaskDifficulty,
        *,
        consecutive_stalls: int = 0,
        requires_browser: bool = False,
        allow_local_fallback: bool = True,
        time_budget: TimeBudget | None = None,
        capacity: LocalCapacity | None = None,
    ) -> ContinuationVerdict:
        if not isinstance(task, Task):
            raise TypeError("task must be a Task instance.")
        if not isinstance(quota, QuotaMetrics):
            raise TypeError("quota must be a QuotaMetrics instance.")
        if not isinstance(difficulty, TaskDifficulty):
            raise TypeError("difficulty must be a TaskDifficulty enum.")
        if type(consecutive_stalls) is not int or consecutive_stalls < 0:
            raise ValueError("consecutive_stalls must be a nonnegative integer.")
        if time_budget is not None and not isinstance(time_budget, TimeBudget):
            raise TypeError("time_budget must be a TimeBudget instance or null.")
        if capacity is not None and not isinstance(capacity, LocalCapacity):
            raise TypeError("capacity must be a LocalCapacity instance or null.")

        if task.risk_class in ("high", "critical"):
            return ContinuationVerdict(
                action=ContinuationAction.REQUIRE_HUMAN,
                target_route=RouteKind.NONE,
                reason=f"Task risk '{task.risk_class}' requires human approval before continuing.",
            )

        if consecutive_stalls >= self.max_consecutive_stalls:
            return ContinuationVerdict(
                action=ContinuationAction.REQUIRE_HUMAN,
                target_route=RouteKind.NONE,
                reason=f"Desynchronization detected: {consecutive_stalls} consecutive stalls without verified progress.",
            )

        short_interactive = (
            time_budget is not None
            and time_budget.interactive
            and time_budget.remaining_seconds < 30.0
        )
        no_time_left = time_budget is not None and time_budget.remaining_seconds <= 0.0
        local_blocked = capacity is not None and not capacity.can_start_local()

        if no_time_left and difficulty != TaskDifficulty.DETERMINISTIC:
            return ContinuationVerdict(
                action=ContinuationAction.REQUIRE_HUMAN,
                target_route=RouteKind.NONE,
                reason="No wall-clock remaining for a non-deterministic step.",
            )

        if requires_browser:
            if local_blocked:
                return ContinuationVerdict(
                    action=ContinuationAction.REQUIRE_HUMAN,
                    target_route=RouteKind.NONE,
                    reason="No local slot or VRAM remaining for a browser MCP session.",
                )
            if no_time_left or short_interactive:
                return ContinuationVerdict(
                    action=ContinuationAction.REQUIRE_HUMAN,
                    target_route=RouteKind.NONE,
                    reason="Browser work needs more wall-clock than the current window allows.",
                )
            if quota.remaining_percent <= self.critical_quota_percent:
                return ContinuationVerdict(
                    action=ContinuationAction.FREEZE_QUOTA,
                    target_route=RouteKind.NONE,
                    reason=f"Quota critical ({quota.remaining_percent:.1f}% <= {self.critical_quota_percent:.1f}%): browser task frozen.",
                )
            return ContinuationVerdict(
                action=ContinuationAction.CONTINUE,
                target_route=RouteKind.WEBBRAIN_MCP,
                reason="Delegated to WebBrain MCP browser session.",
                max_step_tokens=2000 if quota.remaining_percent <= self.moderate_quota_percent else None,
            )

        if difficulty == TaskDifficulty.DETERMINISTIC:
            return ContinuationVerdict(
                action=ContinuationAction.CONTINUE,
                target_route=RouteKind.RULE,
                reason="Deterministic task executed via local rule (0 token cost).",
                max_step_tokens=0,
            )

        if local_blocked and difficulty == TaskDifficulty.COMPACT:
            return ContinuationVerdict(
                action=ContinuationAction.REQUIRE_HUMAN,
                target_route=RouteKind.NONE,
                reason="No local slot or VRAM remaining for a compact local model.",
            )

        if short_interactive and difficulty == TaskDifficulty.REASONING:
            if local_blocked:
                return ContinuationVerdict(
                    action=ContinuationAction.REQUIRE_HUMAN,
                    target_route=RouteKind.NONE,
                    reason="Interactive window needs a local fallback, but no slot or VRAM remains.",
                )
            if quota.remaining_percent <= self.critical_quota_percent or not allow_local_fallback:
                return ContinuationVerdict(
                    action=ContinuationAction.REQUIRE_HUMAN,
                    target_route=RouteKind.NONE,
                    reason="Interactive window too short for reasoning and local fallback is unavailable.",
                )
            return ContinuationVerdict(
                action=ContinuationAction.CONTINUE,
                target_route=RouteKind.LOCAL_SMALL,
                reason="Interactive window too short for frontier reasoning; compact local step only.",
                max_step_tokens=1000,
            )

        if quota.remaining_percent <= self.critical_quota_percent:
            if difficulty == TaskDifficulty.REASONING:
                return ContinuationVerdict(
                    action=ContinuationAction.FREEZE_QUOTA,
                    target_route=RouteKind.NONE,
                    reason=f"Quota critical ({quota.remaining_percent:.1f}% <= {self.critical_quota_percent:.1f}%): heavy reasoning frozen.",
                )
            if allow_local_fallback:
                return ContinuationVerdict(
                    action=ContinuationAction.CONTINUE,
                    target_route=RouteKind.LOCAL_SMALL,
                    reason=f"Quota critical ({quota.remaining_percent:.1f}%): downgraded to local compact model.",
                    max_step_tokens=1000,
                )
            return ContinuationVerdict(
                action=ContinuationAction.FREEZE_QUOTA,
                target_route=RouteKind.NONE,
                reason=f"Quota critical ({quota.remaining_percent:.1f}%) and local fallback disabled.",
            )

        if quota.remaining_percent <= self.moderate_quota_percent:
            if difficulty == TaskDifficulty.REASONING:
                return ContinuationVerdict(
                    action=ContinuationAction.CONTINUE,
                    target_route=RouteKind.FRONTIER,
                    reason=f"Moderate quota ({quota.remaining_percent:.1f}%): reasoning allowed with bounded step tokens.",
                    max_step_tokens=4000,
                )
            return ContinuationVerdict(
                action=ContinuationAction.CONTINUE,
                target_route=RouteKind.LOCAL_SMALL,
                reason=f"Moderate quota ({quota.remaining_percent:.1f}%): compact task routed to small model.",
                max_step_tokens=2000,
            )

        if difficulty == TaskDifficulty.REASONING:
            return ContinuationVerdict(
                action=ContinuationAction.CONTINUE,
                target_route=RouteKind.FRONTIER,
                reason="Nominal quota: full reasoning capacity engaged.",
                max_step_tokens=None,
            )

        return ContinuationVerdict(
            action=ContinuationAction.CONTINUE,
            target_route=RouteKind.LOCAL_SMALL,
            reason="Nominal quota: compact task routed to lightweight model for token conservation.",
            max_step_tokens=None,
        )
