"""Project capability surface, end-of-turn usage reports, and shadow runtime plans.

Parcimonia evaluates a task against a project inventory (skills, plugins, MCP,
tools, KNN/nano/micro routes, local servers) and:
- compares expected vs observed usage at the end of an agent turn
- proposes START / KEEP / IDLE / STOP for the next turn

Nothing here launches, stops, or contacts a server. A plan is always shadow.
Unexpected tool use is a project-control signal, not a prompt to improvise.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from .continuation import LocalCapacity, TaskDifficulty
from .kanban import KanbanTask
from .router import is_nonnegative_number

__all__ = [
    "CapabilityKind",
    "CapabilitySpec",
    "ComplianceVerdict",
    "ProjectSurface",
    "RuntimeAction",
    "RuntimePlan",
    "RuntimePlanItem",
    "RuntimeState",
    "TaskExpectation",
    "UsageEvent",
    "UsageFinding",
    "UsageReport",
    "UsageStatus",
    "compare_usage",
    "expectation_from_kanban_task",
    "ingest_turn_report",
    "plan_runtime",
]


class CapabilityKind(str, Enum):
    RULE = "rule"
    KNN = "knn"
    NANO = "nano"
    MICRO = "micro"
    SKILL = "skill"
    PLUGIN = "plugin"
    MCP = "mcp"
    TOOL = "tool"
    SERVER = "server"


class RuntimeState(str, Enum):
    STOPPED = "stopped"
    IDLE = "idle"
    RUNNING = "running"


class RuntimeAction(str, Enum):
    START = "start"
    KEEP = "keep"
    IDLE = "idle"
    STOP = "stop"


class UsageStatus(str, Enum):
    MATCH = "match"
    MISSING = "missing"
    UNEXPECTED = "unexpected"
    FORBIDDEN = "forbidden"
    UNUSED_ALLOWED = "unused_allowed"


class ComplianceVerdict(str, Enum):
    COMPLIANT = "compliant"
    DRIFT = "drift"
    VIOLATION = "violation"


def _trimmed(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a nonempty, trimmed string.")
    return value


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    kind: CapabilityKind
    keep_warm: bool = False
    idle_cost_per_min: float = 0.0
    startup_cost: float = 0.0

    def __post_init__(self) -> None:
        _trimmed(self.capability_id, "capability_id")
        if not isinstance(self.kind, CapabilityKind):
            raise TypeError("kind must be a CapabilityKind enum.")
        if not is_nonnegative_number(self.idle_cost_per_min):
            raise ValueError("idle_cost_per_min must be a finite nonnegative number.")
        if not is_nonnegative_number(self.startup_cost):
            raise ValueError("startup_cost must be a finite nonnegative number.")


@dataclass(frozen=True)
class ProjectSurface:
    project_id: str
    capabilities: tuple[CapabilitySpec, ...]

    def __post_init__(self) -> None:
        _trimmed(self.project_id, "project_id")
        if not self.capabilities:
            raise ValueError("a project surface needs at least one capability.")
        ids = [item.capability_id for item in self.capabilities]
        if len(set(ids)) != len(ids):
            raise ValueError("capability ids must be unique.")

    def get(self, capability_id: str) -> CapabilitySpec | None:
        for item in self.capabilities:
            if item.capability_id == capability_id:
                return item
        return None

    def known(self) -> frozenset[str]:
        return frozenset(item.capability_id for item in self.capabilities)


@dataclass(frozen=True)
class TaskExpectation:
    """What a project allows an agent to use for one task.

    `required` must appear in the end-of-turn usage. `allowed` may appear.
    `forbidden` always wins. Anything else is unexpected.
    """

    task_id: str
    required: tuple[str, ...] = ()
    allowed: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _trimmed(self.task_id, "task_id")
        for label, values in (
            ("required", self.required),
            ("allowed", self.allowed),
            ("forbidden", self.forbidden),
        ):
            seen: set[str] = set()
            for item in values:
                _trimmed(item, f"{label} entry")
                if item in seen:
                    raise ValueError(f"{label} must not repeat {item!r}.")
                seen.add(item)
        overlap = set(self.required) & set(self.forbidden)
        if overlap:
            raise ValueError(f"required capabilities cannot also be forbidden: {sorted(overlap)}.")

    def permitted(self) -> frozenset[str]:
        return (frozenset(self.required) | frozenset(self.allowed)) - frozenset(self.forbidden)


@dataclass(frozen=True)
class UsageEvent:
    capability_id: str
    count: int = 1
    tokens: int | None = None

    def __post_init__(self) -> None:
        _trimmed(self.capability_id, "capability_id")
        if type(self.count) is not int or self.count < 1:
            raise ValueError("count must be a positive integer.")
        if self.tokens is not None and (type(self.tokens) is not int or self.tokens < 0):
            raise ValueError("tokens must be null or a nonnegative integer.")


@dataclass(frozen=True)
class UsageFinding:
    capability_id: str
    status: UsageStatus
    expected: bool
    observed: bool
    detail: str


@dataclass(frozen=True)
class UsageReport:
    task_id: str
    project_id: str
    verdict: ComplianceVerdict
    findings: tuple[UsageFinding, ...]
    used: tuple[str, ...]
    data_origin: str = "caller_reported"

    def missing(self) -> tuple[str, ...]:
        return tuple(item.capability_id for item in self.findings if item.status is UsageStatus.MISSING)

    def forbidden_used(self) -> tuple[str, ...]:
        return tuple(item.capability_id for item in self.findings if item.status is UsageStatus.FORBIDDEN)

    def unexpected(self) -> tuple[str, ...]:
        return tuple(item.capability_id for item in self.findings if item.status is UsageStatus.UNEXPECTED)


@dataclass(frozen=True)
class RuntimePlanItem:
    capability_id: str
    action: RuntimeAction
    from_state: RuntimeState
    to_state: RuntimeState
    reason: str
    shadow: bool = True


@dataclass(frozen=True)
class RuntimePlan:
    task_id: str
    project_id: str
    items: tuple[RuntimePlanItem, ...]
    executed: bool = False

    def actions(self) -> dict[str, RuntimeAction]:
        return {item.capability_id: item.action for item in self.items}


def expectation_from_kanban_task(task: KanbanTask) -> TaskExpectation:
    """Derive a conservative allowlist from a local kanban card."""
    required: list[str] = []
    allowed = ["route:rule", "route:knn", "skill:verification"]
    forbidden: list[str] = []
    if task.requires_browser:
        required.append("mcp:webbrain")
        allowed.append("mcp:webbrain")
    if task.difficulty is TaskDifficulty.DETERMINISTIC:
        required.append("route:rule")
        forbidden.append("route:frontier")
    elif task.difficulty is TaskDifficulty.COMPACT:
        allowed.extend(["route:nano", "route:micro", "tool:schema_emit"])
    else:
        allowed.extend(["route:micro", "route:frontier", "tool:schema_emit"])
    # Preserve order while dropping duplicates introduced by required+allowed.
    allowed_unique = tuple(dict.fromkeys(allowed))
    return TaskExpectation(
        task_id=task.task_id,
        required=tuple(dict.fromkeys(required)),
        allowed=allowed_unique,
        forbidden=tuple(dict.fromkeys(forbidden)),
    )


def compare_usage(
    surface: ProjectSurface,
    expectation: TaskExpectation,
    events: Sequence[UsageEvent],
) -> UsageReport:
    if not isinstance(surface, ProjectSurface):
        raise TypeError("surface must be a ProjectSurface instance.")
    if not isinstance(expectation, TaskExpectation):
        raise TypeError("expectation must be a TaskExpectation instance.")

    used_counts: dict[str, int] = {}
    for event in events:
        if not isinstance(event, UsageEvent):
            raise TypeError("events must contain UsageEvent instances.")
        used_counts[event.capability_id] = used_counts.get(event.capability_id, 0) + event.count
    used = tuple(sorted(used_counts))
    known = surface.known()
    forbidden = set(expectation.forbidden)
    required = set(expectation.required)
    permitted = set(expectation.permitted())
    findings: list[UsageFinding] = []

    for capability_id in sorted(required):
        observed = capability_id in used_counts
        if not observed:
            findings.append(
                UsageFinding(
                    capability_id=capability_id,
                    status=UsageStatus.MISSING,
                    expected=True,
                    observed=False,
                    detail="Required capability was not used in this turn.",
                )
            )
        elif capability_id in forbidden:
            findings.append(
                UsageFinding(
                    capability_id=capability_id,
                    status=UsageStatus.FORBIDDEN,
                    expected=True,
                    observed=True,
                    detail="Capability is forbidden by the project profile.",
                )
            )
        else:
            findings.append(
                UsageFinding(
                    capability_id=capability_id,
                    status=UsageStatus.MATCH,
                    expected=True,
                    observed=True,
                    detail="Required capability was used.",
                )
            )

    for capability_id in used:
        if capability_id in required:
            continue
        if capability_id in forbidden:
            findings.append(
                UsageFinding(
                    capability_id=capability_id,
                    status=UsageStatus.FORBIDDEN,
                    expected=False,
                    observed=True,
                    detail="Forbidden capability was used.",
                )
            )
            continue
        if capability_id not in known:
            findings.append(
                UsageFinding(
                    capability_id=capability_id,
                    status=UsageStatus.UNEXPECTED,
                    expected=False,
                    observed=True,
                    detail="Capability is not in the project surface.",
                )
            )
            continue
        if capability_id not in permitted:
            findings.append(
                UsageFinding(
                    capability_id=capability_id,
                    status=UsageStatus.UNEXPECTED,
                    expected=False,
                    observed=True,
                    detail="Capability is outside the task allowlist.",
                )
            )
            continue
        findings.append(
            UsageFinding(
                capability_id=capability_id,
                status=UsageStatus.MATCH,
                expected=True,
                observed=True,
                detail="Allowed capability was used.",
            )
        )

    for capability_id in sorted(permitted - required - set(used)):
        findings.append(
            UsageFinding(
                capability_id=capability_id,
                status=UsageStatus.UNUSED_ALLOWED,
                expected=False,
                observed=False,
                detail="Allowed capability was idle this turn.",
            )
        )

    statuses = {item.status for item in findings}
    if UsageStatus.FORBIDDEN in statuses or UsageStatus.UNEXPECTED in statuses:
        verdict = ComplianceVerdict.VIOLATION
    elif UsageStatus.MISSING in statuses:
        verdict = ComplianceVerdict.DRIFT
    else:
        verdict = ComplianceVerdict.COMPLIANT

    return UsageReport(
        task_id=expectation.task_id,
        project_id=surface.project_id,
        verdict=verdict,
        findings=tuple(findings),
        used=used,
    )


def _target_state(action: RuntimeAction, current: RuntimeState) -> RuntimeState:
    if action is RuntimeAction.START:
        return RuntimeState.RUNNING
    if action is RuntimeAction.STOP:
        return RuntimeState.STOPPED
    if action is RuntimeAction.IDLE:
        return RuntimeState.IDLE
    return current


_SLOT_KINDS = frozenset(
    {
        CapabilityKind.NANO,
        CapabilityKind.MICRO,
        CapabilityKind.MCP,
        CapabilityKind.SERVER,
        CapabilityKind.TOOL,
    }
)


def _needs_local_slot(spec: CapabilitySpec) -> bool:
    return spec.kind in _SLOT_KINDS or spec.keep_warm


def plan_runtime(
    surface: ProjectSurface,
    expectation: TaskExpectation,
    current: Mapping[str, RuntimeState],
    *,
    observed: Sequence[UsageEvent] = (),
    capacity: LocalCapacity | None = None,
) -> RuntimePlan:
    """Propose runtime changes without executing them.

    Required capabilities are started or kept. Unused expensive processes are
    idled or stopped. Forbidden capabilities are stopped. Presence in `observed`
    only keeps a permitted capability warm; it never authorizes a forbidden one.
    """
    if not isinstance(surface, ProjectSurface):
        raise TypeError("surface must be a ProjectSurface instance.")
    if not isinstance(expectation, TaskExpectation):
        raise TypeError("expectation must be a TaskExpectation instance.")
    if capacity is not None and not isinstance(capacity, LocalCapacity):
        raise TypeError("capacity must be a LocalCapacity instance or null.")

    used = {event.capability_id for event in observed}
    required = set(expectation.required)
    permitted = set(expectation.permitted())
    forbidden = set(expectation.forbidden)
    items: list[RuntimePlanItem] = []

    for spec in surface.capabilities:
        cid = spec.capability_id
        state = current.get(cid, RuntimeState.STOPPED)
        if not isinstance(state, RuntimeState):
            raise TypeError(f"current[{cid!r}] must be a RuntimeState.")

        if cid in forbidden:
            action = RuntimeAction.STOP if state is not RuntimeState.STOPPED else RuntimeAction.KEEP
            reason = "Forbidden by the project profile; stop or keep stopped."
        elif cid in required:
            action = RuntimeAction.KEEP if state is RuntimeState.RUNNING else RuntimeAction.START
            reason = "Required for the task; start or keep running."
        elif cid in used and cid in permitted:
            action = RuntimeAction.KEEP if state is RuntimeState.RUNNING else RuntimeAction.START
            reason = "Used this turn and allowed; keep warm."
        else:
            if state is RuntimeState.STOPPED:
                action = RuntimeAction.KEEP
                reason = "Unused and already stopped."
            elif spec.keep_warm and state in (RuntimeState.RUNNING, RuntimeState.IDLE):
                action = RuntimeAction.IDLE if state is RuntimeState.RUNNING else RuntimeAction.KEEP
                reason = "Unused but keep_warm; park idle instead of unloading."
            elif spec.idle_cost_per_min > 0 or state is RuntimeState.RUNNING:
                action = RuntimeAction.STOP
                reason = "Unused; stop to release local slots and idle cost."
            else:
                action = RuntimeAction.KEEP
                reason = "Unused idle process with no idle cost; leave as is."

        if (
            capacity is not None
            and not capacity.can_start_local()
            and _needs_local_slot(spec)
        ):
            if action is RuntimeAction.START:
                action = RuntimeAction.KEEP
                reason = "No local slot or VRAM; start withheld."
            elif cid not in required and state in (RuntimeState.RUNNING, RuntimeState.IDLE):
                action = RuntimeAction.STOP
                reason = "No local slot or VRAM; unused process stopped in the shadow plan."

        items.append(
            RuntimePlanItem(
                capability_id=cid,
                action=action,
                from_state=state,
                to_state=_target_state(action, state),
                reason=reason,
                shadow=True,
            )
        )

    unknown_required = sorted(required - surface.known())
    for cid in unknown_required:
        items.append(
            RuntimePlanItem(
                capability_id=cid,
                action=RuntimeAction.KEEP,
                from_state=RuntimeState.STOPPED,
                to_state=RuntimeState.STOPPED,
                reason="Required but absent from the project surface; fail closed, do not invent a process.",
                shadow=True,
            )
        )

    return RuntimePlan(
        task_id=expectation.task_id,
        project_id=surface.project_id,
        items=tuple(items),
        executed=False,
    )


_TURN_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "task_id",
        "skills",
        "tools",
        "mcp",
        "plugins",
        "routes",
        "servers",
    }
)
_TURN_BUCKETS = (
    ("skills", "skill"),
    ("tools", "tool"),
    ("mcp", "mcp"),
    ("plugins", "plugin"),
    ("routes", "route"),
    ("servers", "server"),
)
_EVENT_FIELDS = frozenset({"id", "count", "tokens"})


def ingest_turn_report(payload: object) -> tuple[UsageEvent, ...]:
    """Parse a structured end-of-turn usage report into events.

    This does not scrape a chat UI. Unknown keys are rejected. Empty buckets
    yield no events. Ids are prefixed by bucket unless already prefixed.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("turn report must be a mapping.")
    if set(payload) != _TURN_FIELDS:
        raise ValueError(f"turn report must contain exactly {sorted(_TURN_FIELDS)}.")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported turn report schema_version; expected 1.")
    if payload.get("kind") != "turn_usage":
        raise ValueError("kind must be 'turn_usage'.")
    _trimmed(payload.get("task_id"), "task_id")

    events: list[UsageEvent] = []
    for bucket, prefix in _TURN_BUCKETS:
        raw = payload.get(bucket)
        if not isinstance(raw, list):
            raise ValueError(f"{bucket} must be a list.")
        for index, item in enumerate(raw):
            label = f"{bucket}[{index}]"
            if not isinstance(item, Mapping):
                raise ValueError(f"{label} must be a mapping.")
            extra = set(item) - _EVENT_FIELDS
            if extra:
                raise ValueError(f"{label} has unknown keys {sorted(extra)}.")
            if "id" not in item:
                raise ValueError(f"{label} must include id.")
            identifier = _trimmed(item["id"], f"{label}.id")
            if ":" in identifier:
                if not identifier.startswith(prefix + ":"):
                    raise ValueError(
                        f"{label}.id {identifier!r} does not match bucket prefix {prefix!r}."
                    )
                capability_id = identifier
            else:
                capability_id = f"{prefix}:{identifier}"
            count = item.get("count", 1)
            tokens = item.get("tokens")
            events.append(UsageEvent(capability_id=capability_id, count=count, tokens=tokens))
    return tuple(events)
