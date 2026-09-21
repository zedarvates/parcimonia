"""Optional local reflex backend probe.

Fails closed unless load is explicitly authorized and a local weights file
already exists. This module never downloads, never calls a hub, and never
imports third-party decision engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["OptionalLocalBackendStatus", "probe_optional_local_backend"]


@dataclass(frozen=True)
class OptionalLocalBackendStatus:
    available: bool
    reason: str
    path: str | None
    allow_load: bool


def probe_optional_local_backend(
    path: str | Path | None,
    *,
    allow_load: bool = False,
) -> OptionalLocalBackendStatus:
    rendered = None if path is None else str(path)
    if not allow_load:
        return OptionalLocalBackendStatus(
            available=False,
            reason="load not authorized; download is not performed.",
            path=rendered,
            allow_load=False,
        )
    if path is None:
        return OptionalLocalBackendStatus(
            available=False,
            reason="no weights path configured; download is not performed.",
            path=None,
            allow_load=True,
        )
    candidate = Path(path)
    if not candidate.is_file():
        return OptionalLocalBackendStatus(
            available=False,
            reason="weights file missing; download is not performed.",
            path=str(candidate),
            allow_load=True,
        )
    return OptionalLocalBackendStatus(
        available=False,
        reason="weight loading is not implemented; local file present but unused.",
        path=str(candidate),
        allow_load=True,
    )

