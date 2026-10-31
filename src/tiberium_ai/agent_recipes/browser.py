"""Snapshot-bound control selection, bounded execution and independent completion."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from .core import DecisionSession, Proposal, abstain, fingerprint, propose


@dataclass(frozen=True)
class Control:
    id: str
    label: str
    action: str = "click"


@dataclass(frozen=True)
class BrowserSnapshot:
    version: str
    url: str
    controls: tuple[Control, ...]

    def __post_init__(self) -> None:
        ids = [c.id for c in self.controls]
        if not self.version or len(set(ids)) != len(ids) or any(not i for i in ids):
            raise ValueError("invalid browser snapshot")
        if any(c.action not in {"click", "focus"} for c in self.controls):
            raise ValueError("unsupported browser action")


class BrowserRunner:
    """Host provides observation, authority, execution and a goal verifier.

    No browser package or implicit credentials. Without approve, return a proposal.
    A semantic 'done' answer never certifies the goal.
    """
    def __init__(self, session: DecisionSession, *, max_steps: int = 10) -> None:
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.session, self.max_steps = session, max_steps

    def run(self, goal: str, *, observe: Callable[[], BrowserSnapshot],
            verify_goal: Callable[[BrowserSnapshot], bool],
            execute: Callable[[Control, str], None],
            approve: Callable[[Control, BrowserSnapshot], bool] | None = None) -> Proposal:
        history, seen = [], set()
        first = observe()
        state = {"goal": goal, "initial": asdict(first)}
        snapshot = first
        for step in range(self.max_steps + 1):
            if verify_goal(snapshot) is True:
                return Proposal("browser.navigate@1", "verified", "host_goal_verifier",
                                fingerprint(state), {"history": history, "final": asdict(snapshot)})
            if step == self.max_steps:
                return abstain("browser.navigate@1", state, ValueError("step_limit"), history)
            # Version is freshness, content is loop detection.
            content = fingerprint({"url": snapshot.url, "controls": [asdict(c) for c in snapshot.controls]})
            if content in seen:
                return Proposal("browser.navigate@1", "abstained", "loop_detected", fingerprint(state), history)
            seen.add(content)
            if len(snapshot.controls) > 18:
                return Proposal("browser.navigate@1", "abstained", "shortlist_required", fingerprint(state), history)
            options = {f"c{i}": c.label for i, c in enumerate(snapshot.controls)}
            options.update(done="Goal appears complete", blocked="No valid action available")
            try:
                selected = self.session.choice({"goal": goal, "snapshot": asdict(snapshot)}, options)
            except (ValueError, TypeError, KeyError, OSError) as error:
                return abstain("browser.navigate@1", state, error, history)
            if selected in {"done", "blocked"}:
                return Proposal("browser.navigate@1", "abstained", "goal_not_verified", fingerprint(state), history)
            control = snapshot.controls[int(selected[1:])]
            fresh = observe()
            if fingerprint(asdict(fresh)) != fingerprint(asdict(snapshot)):
                return Proposal("browser.navigate@1", "abstained", "stale_snapshot", fingerprint(state), history)
            if approve is None or approve(control, fresh) is not True:
                return propose("browser.navigate@1", state,
                               {"control": asdict(control), "snapshot": snapshot.version, "history": history},
                               "host_authorization_required")
            # The executor must atomically compare version immediately before its action.
            execute(control, snapshot.version)
            snapshot = observe()
            history.append({"control": asdict(control), "before": fresh.version, "after": snapshot.version})
        raise AssertionError("unreachable")
