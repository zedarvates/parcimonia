"""Local, content-addressed store of audit verdicts.

The store answers one question cheaply: has this exact file, under this exact
rule policy, already been audited? That is the cheapest route Parcimonia can
take, and it is also the one that most easily turns into a stale claim, so the
key is ``(content hash, policy version)`` and the policy version already
contains the rule fingerprint and the role suppressions.

Three rules keep reuse honest:

* nothing but a hash, counts and ratios is stored: no source text, no path, no
  task input, so a leak of the database does not leak a repository
* a second record with the same key and a different verdict is refused as a
  determinism failure, not overwritten
* only records whose provenance is ``measured`` and whose band is determined are
  ever offered for reuse; fixture and synthetic provenance is observability, and
  an undetermined verdict is an abstention, not a cached answer

The stores never reads a clock: ``recorded_at`` is supplied by the caller, which
keeps recording reproducible.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .audit_score import DIMENSION_NAMES

__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "DATA_ORIGINS",
    "AuditRecord",
    "SqliteAuditStore",
]

ANALYSIS_SCHEMA_VERSION = 1

#: Provenance values a record may declare. ``observed`` is deliberately absent:
#: a static audit either ran on real text or ran on authored fixtures.
DATA_ORIGINS = frozenset({"measured", "fixture", "synthetic"})

_COLUMNS = (
    "recorded_at",
    "content_hash",
    "project_id",
    "policy_version",
    "role",
    "role_reason",
    "band",
    "deficit",
    "dimensions",
    "skipped",
    "rule_counts",
    "attribution",
    "findings_total",
    "data_origin",
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS analysis (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at    TEXT    NOT NULL,
    content_hash   TEXT    NOT NULL,
    project_id     TEXT    NOT NULL,
    policy_version TEXT    NOT NULL,
    role           TEXT    NOT NULL,
    role_reason    TEXT    NOT NULL,
    band           TEXT    NOT NULL,
    deficit        REAL,
    dimensions     TEXT    NOT NULL,
    skipped        TEXT    NOT NULL,
    rule_counts    TEXT    NOT NULL,
    attribution    TEXT    NOT NULL,
    findings_total INTEGER NOT NULL,
    data_origin    TEXT    NOT NULL,
    UNIQUE (content_hash, policy_version)
);
CREATE INDEX IF NOT EXISTS analysis_content_hash ON analysis(content_hash);
"""


def _dumps(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonempty, trimmed string.")
    return value


@dataclass(frozen=True)
class AuditRecord:
    """One stored audit verdict, stripped of every input it was computed from."""

    recorded_at: str
    project_id: str
    policy_version: str
    content_hash: str
    role: str
    role_reason: str
    band: str
    deficit: float | None
    dimensions: Mapping[str, float]
    skipped: Sequence[str]
    rule_counts: Mapping[str, int]
    attribution: Mapping[str, float]
    findings_total: int
    data_origin: str

    def __post_init__(self) -> None:
        for name in ("recorded_at", "project_id", "policy_version", "role", "role_reason", "band"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        content_hash = self.content_hash
        if (
            not isinstance(content_hash, str)
            or len(content_hash) != 64
            or any(character not in "0123456789abcdef" for character in content_hash)
        ):
            raise ValueError("content_hash must be 64 lowercase hexadecimal characters.")
        if self.data_origin not in DATA_ORIGINS:
            raise ValueError(
                f"data_origin must be one of {sorted(DATA_ORIGINS)}; got {self.data_origin!r}."
            )
        if self.band == "undetermined":
            if self.deficit is not None:
                raise ValueError("an undetermined audit must not carry a deficit.")
        elif self.deficit is None:
            raise ValueError("a determined audit must carry a deficit.")
        if self.deficit is not None:
            if isinstance(self.deficit, bool) or not isinstance(self.deficit, (int, float)):
                raise ValueError("deficit must be a number between 0 and 100.")
            if not 0.0 <= float(self.deficit) <= 100.0:
                raise ValueError("deficit must be between 0 and 100.")
            object.__setattr__(self, "deficit", float(self.deficit))

        dimensions = dict(self.dimensions)
        unknown = sorted(set(dimensions) - set(DIMENSION_NAMES))
        if unknown:
            raise ValueError(f"unknown dimension(s) {unknown} in record.")
        for name, value in dimensions.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"dimension {name!r} must be a number in [0, 1].")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"dimension {name!r} must be between 0 and 1.")
            dimensions[name] = float(value)
        object.__setattr__(self, "dimensions", dimensions)

        skipped = tuple(self.skipped)
        if len(set(skipped)) != len(skipped):
            raise ValueError("skipped dimensions must not repeat.")
        for name in skipped:
            if name not in dimensions:
                raise ValueError(f"skipped dimension {name!r} was never recorded.")
        object.__setattr__(self, "skipped", skipped)

        counts = dict(self.rule_counts)
        for rule_id, count in counts.items():
            _require_text(rule_id, "rule_counts key")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("rule_counts values must be nonnegative integers.")
        object.__setattr__(self, "rule_counts", counts)

        attribution = {name: float(value) for name, value in self.attribution.items()}
        object.__setattr__(self, "attribution", attribution)

        if (
            isinstance(self.findings_total, bool)
            or not isinstance(self.findings_total, int)
            or self.findings_total < 0
        ):
            raise ValueError("findings_total must be a nonnegative integer.")

    @property
    def reusable(self) -> bool:
        """Whether this record may be replayed as a previous verdict."""
        return self.data_origin == "measured" and self.band != "undetermined"

    def same_verdict(self, other: "AuditRecord") -> bool:
        """Compare the verdict-bearing fields, ignoring when it was recorded."""
        return self.normalised_verdict() == other.normalised_verdict()

    def normalised_verdict(self) -> dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "project_id": self.project_id,
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
            "data_origin": self.data_origin,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "audit_record", **self.normalised_verdict(), "recorded_at": self.recorded_at}


class SqliteAuditStore:
    """Local SQLite store keyed by content hash and policy version."""

    def __init__(self, path: str | Path) -> None:
        if isinstance(path, Path):
            path = str(path)
        if not isinstance(path, str) or not path or path != path.strip():
            raise ValueError("path must be a nonempty, trimmed string.")
        if path != ":memory:":
            parent = Path(path).parent
            if str(parent) and not parent.exists():
                raise FileNotFoundError(
                    f"parent directory {parent} must exist; the store never creates it."
                )
        self._path = path
        self._connection = self._open()

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SqliteAuditStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def record(self, record: AuditRecord) -> bool:
        """Store a verdict. Return True when inserted, False when identical.

        A second verdict for the same ``(content_hash, policy_version)`` that
        disagrees with the stored one raises: the audit is claimed to be
        deterministic, so a disagreement is a defect to surface, not a conflict
        to resolve silently.
        """
        if not isinstance(record, AuditRecord):
            raise TypeError("record must be an AuditRecord instance.")
        existing = self._find(record.content_hash, record.policy_version)
        if existing is not None:
            if existing.same_verdict(record):
                return False
            raise ValueError(
                "a different verdict is already stored for this content hash and policy "
                "version; the deterministic audit is not reproducible."
            )
        with self._connection:
            self._connection.execute(
                f"INSERT INTO analysis ({', '.join(_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
                (
                    record.recorded_at,
                    record.content_hash,
                    record.project_id,
                    record.policy_version,
                    record.role,
                    record.role_reason,
                    record.band,
                    record.deficit,
                    _dumps(dict(record.dimensions)),
                    _dumps(list(record.skipped)),
                    _dumps(dict(record.rule_counts)),
                    _dumps(dict(record.attribution)),
                    record.findings_total,
                    record.data_origin,
                ),
            )
        return True

    def reuse(self, content_hash: str, policy_version: str) -> AuditRecord | None:
        """Return a previously measured, determined verdict, or None."""
        _require_text(policy_version, "policy_version")
        found = self._find(content_hash, policy_version)
        if found is None or not found.reusable:
            return None
        return found

    def history(self, content_hash: str) -> tuple[AuditRecord, ...]:
        """Return every record stored for one content hash, oldest first."""
        if not isinstance(content_hash, str):
            raise TypeError("content_hash must be a string.")
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM analysis WHERE content_hash = ? ORDER BY id",
            (content_hash,),
        ).fetchall()
        return tuple(_from_row(row) for row in rows)

    def count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM analysis").fetchone()[0])

    def export_jsonl(self, path: str | Path) -> int:
        """Write one canonical JSON line per record, never overwriting a file."""
        target = Path(path)
        if str(target.parent) and not target.parent.exists():
            raise FileNotFoundError(f"parent directory {target.parent} must exist.")
        if target.exists():
            raise FileExistsError(f"{target} already exists; export never overwrites.")
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM analysis ORDER BY id"
        ).fetchall()
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(_dumps(_from_row(row).to_dict()) + "\n")
        return len(rows)

    def _find(self, content_hash: str, policy_version: str) -> AuditRecord | None:
        if not isinstance(content_hash, str):
            raise TypeError("content_hash must be a string.")
        _require_text(policy_version, "policy_version")
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM analysis "
            "WHERE content_hash = ? AND policy_version = ?",
            (content_hash, policy_version),
        ).fetchone()
        return None if row is None else _from_row(row)

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                with connection:
                    connection.executescript(_SCHEMA)
                    connection.execute(f"PRAGMA user_version = {ANALYSIS_SCHEMA_VERSION}")
            elif version != ANALYSIS_SCHEMA_VERSION:
                raise ValueError(
                    f"analysis store schema version {version} is unknown; refusing to write "
                    f"to a store this build does not understand (expected "
                    f"{ANALYSIS_SCHEMA_VERSION})."
                )
        except Exception:
            connection.close()
            raise
        return connection


def _from_row(row: Sequence[Any]) -> AuditRecord:
    values = dict(zip(_COLUMNS, row))
    return AuditRecord(
        recorded_at=values["recorded_at"],
        project_id=values["project_id"],
        policy_version=values["policy_version"],
        content_hash=values["content_hash"],
        role=values["role"],
        role_reason=values["role_reason"],
        band=values["band"],
        deficit=values["deficit"],
        dimensions=json.loads(values["dimensions"]),
        skipped=json.loads(values["skipped"]),
        rule_counts=json.loads(values["rule_counts"]),
        attribution=json.loads(values["attribution"]),
        findings_total=values["findings_total"],
        data_origin=values["data_origin"],
    )
