"""Incremental skill metadata and idempotent usage events in local SQLite."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Any, Sequence

from .core import fingerprint


def terms(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]{3,}", text.casefold()))


def utc_stamp(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp needs timezone")
    return dt.astimezone(timezone.utc).isoformat()


def _metadata(text: str, fallback: str) -> tuple[str, str]:
    """Support plain front matter and YAML block descriptions without a dependency."""
    name, description = fallback, ""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            raise ValueError("unterminated front matter")
        header = lines[1:end]
        for i, line in enumerate(header):
            if line.startswith("name:"):
                name = line[5:].strip().strip("\"'") or fallback
            if line.startswith("description:"):
                value = line[12:].strip()
                if value in ("|", ">", "|-", ">-"):
                    parts = []
                    for following in header[i + 1:]:
                        if following and not following[0].isspace():
                            break
                        parts.append(following.strip())
                    value = " ".join(parts)
                description = value.strip("\"'")
    if not description:
        description = " ".join(l.strip() for l in lines if l.strip() and not l.startswith("#"))[:1200]
    return name, description


class SkillCatalog:
    def __init__(self, path: str | Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY, root TEXT NOT NULL, path TEXT NOT NULL,
                name TEXT NOT NULL, description TEXT NOT NULL, content_hash TEXT NOT NULL,
                indexed_at TEXT NOT NULL, present INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS usage (
                event_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL,
                at TEXT NOT NULL, outcome TEXT NOT NULL);
        """)

    def __enter__(self) -> SkillCatalog:
        return self

    def __exit__(self, *args: Any) -> None:
        self.connection.close()

    def sync(self, root: str | Path, *, at: str) -> dict[str, Any]:
        directory = Path(root).resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("skill root must be a directory")
        at = utc_stamp(at)
        root_id = str(directory)
        discovered = []
        # Build the complete snapshot before changing the DB. Failed reads leave it intact.
        for path in sorted(directory.rglob("SKILL.md")):
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(directory):
                raise ValueError("skill path escapes root")
            if resolved.stat().st_size > 262144:
                raise ValueError("skill exceeds metadata read budget")
            text = resolved.read_text(encoding="utf-8-sig")
            name, description = _metadata(text, path.parent.name)
            skill_id = fingerprint({"root": root_id, "path": str(path.relative_to(directory))})
            discovered.append((skill_id, root_id, str(resolved), name, description,
                               fingerprint(text), at, 1))
        added = changed = unchanged = 0
        with self.connection:
            previous = {r["id"]: dict(r) for r in self.connection.execute(
                "SELECT * FROM skills WHERE root=?", (root_id,))}
            current_ids = {r[0] for r in discovered}
            for row in discovered:
                old = previous.get(row[0])
                if old and old["content_hash"] == row[5] and old["present"]:
                    unchanged += 1
                    continue
                added += old is None
                changed += old is not None
                self.connection.execute("INSERT OR REPLACE INTO skills VALUES (?,?,?,?,?,?,?,?)", row)
            removed = [i for i, r in previous.items() if r["present"] and i not in current_ids]
            for i in removed:
                self.connection.execute("UPDATE skills SET present=0 WHERE id=?", (i,))
        return {"added": added, "changed": changed, "unchanged": unchanged, "removed": len(removed)}

    def record_use(self, skill_id: str, *, event_id: str, at: str, outcome: str) -> bool:
        if not event_id.strip() or outcome not in {"success", "failure", "unknown"}:
            raise ValueError("invalid usage event")
        at = utc_stamp(at)
        if not self.connection.execute("SELECT 1 FROM skills WHERE id=?", (skill_id,)).fetchone():
            raise ValueError("unknown skill")
        existing = self.connection.execute("SELECT * FROM usage WHERE event_id=?", (event_id,)).fetchone()
        if existing:
            if (existing["skill_id"], existing["at"], existing["outcome"]) != (skill_id, at, outcome):
                raise ValueError("event id reused with different content")
            return False
        with self.connection:
            self.connection.execute("INSERT INTO usage VALUES (?,?,?,?)", (event_id, skill_id, at, outcome))
        return True

    def rows(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.connection.execute("""
            SELECT s.*, COUNT(u.event_id) AS uses, MAX(u.at) AS last_used,
                SUM(CASE WHEN u.outcome='success' THEN 1 ELSE 0 END) AS successes
            FROM skills s LEFT JOIN usage u ON u.skill_id=s.id
            WHERE s.present=1 GROUP BY s.id ORDER BY s.id
        """)]

    def shortlist(self, query: str, *, limit: int = 12,
                  eligible_ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 19:
            raise ValueError("shortlist limit must be 1..19 (plus none)")
        query_terms = terms(query)
        allowed = None if eligible_ids is None else set(eligible_ids)
        scored = []
        for row in self.rows():
            if allowed is not None and row["id"] not in allowed:
                continue
            score = len(query_terms & terms(row["name"] + " " + row["description"]))
            if score:
                scored.append({**row, "lexical_overlap": score})
        return sorted(scored, key=lambda r: (-r["lexical_overlap"], r["id"]))[:limit]
