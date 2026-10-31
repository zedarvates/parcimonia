"""Content-addressed response reuse; only schema-validated answers enter the cache."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from typing import Any, Sequence

from ..reflex import InjectedReflexBackend, ReflexBackend, ReflexEngine, ReflexQuestion
from .core import canonical, fingerprint


class CachedBackend:
    def __init__(self, backend: ReflexBackend, path: str | Path, *, identity: str) -> None:
        if not identity.strip():
            raise ValueError("cache identity must include backend and pinned version")
        self.backend, self.identity = backend, identity
        self.backend_id = "cache:" + identity
        self.latin_only = getattr(backend, "latin_only", False)
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.last_usage: dict[str, Any] = {}
        self.last_model = None

    def close(self) -> None:
        self.connection.close()

    def evaluate(self, state_text: str, questions: Sequence[ReflexQuestion]) -> dict[str, Any]:
        self.last_usage, self.last_model = {}, None
        key = fingerprint({"schema": 1, "identity": self.identity, "state": state_text,
                           "questions": [asdict(q) for q in questions]})
        row = self.connection.execute("SELECT payload FROM responses WHERE key=?", (key,)).fetchone()
        if row:
            answers = json.loads(row[0])
            ReflexEngine(InjectedReflexBackend(answers, latin_only=self.latin_only)).evaluate(state_text, questions)
            self.last_usage = {"input_tokens": 0, "output_tokens": 0, "billed_cost": 0,
                               "origin": "cache", "original_backend": self.identity}
            return answers
        raw = self.backend.evaluate(state_text, questions)
        batch = ReflexEngine(InjectedReflexBackend(raw, latin_only=self.latin_only)).evaluate(state_text, questions)
        if batch.refused_script:
            raise ValueError("script_refused")
        if set(raw) != {q.name for q in questions}:
            raise ValueError("incomplete or extra answers")
        answers = {k: dict(v) for k, v in raw.items()}
        with self.connection:
            self.connection.execute("INSERT INTO responses VALUES (?,?)", (key, canonical(answers)))
        self.last_usage = dict(getattr(self.backend, "last_usage", {}))
        self.last_model = getattr(self.backend, "last_model", None)
        return answers
