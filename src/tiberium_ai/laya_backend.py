"""Optional Laya SDK bridge. Import/construction never loads neural weights."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

from .reflex import InjectedReflexBackend, ReflexEngine, ReflexQuestion
from .provider_answers import NORMALIZER_VERSION, normalize_systemone_answers


class LayaBackend:
    """Explicitly loaded multilingual checkpoint; no automatic routing or retries.

    Provider confidence is retained for shadow evaluation, not authorization.
    A predictor may be injected for offline contract tests.
    """

    latin_only = False
    backend_id = "laya.sdk.multilingual@1"

    def __init__(self, *, revision: str, predict: Callable[..., Mapping[str, Any]],
                 runtime_version: str, max_calls: int = 100, max_len: int = 8192):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("an immutable checkpoint SHA is required")
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls must be positive")
        if type(max_len) is not int or not 1 <= max_len <= 8192:
            raise ValueError("max_len must be in [1, 8192]")
        if not runtime_version or not callable(predict):
            raise ValueError("runtime version and predictor required")
        self.revision, self.runtime_version = revision, runtime_version
        self.model = "convaiinnovations/laya/multilingual@" + revision
        self._predict, self.max_calls, self.max_len = predict, max_calls, max_len
        self.calls = 0
        self.device: str | None = None
        self.last_usage: dict[str, Any] = {}
        self.last_raw_answers: dict[str, Any] = {}

    @property
    def backend_version(self) -> str:
        return (f"{self.model}|sdk={self.runtime_version}|runtime={getattr(self, 'runtime_revision', None)}"
                f"|device={self.device}|{NORMALIZER_VERSION}")

    @classmethod
    def load(cls, *, revision: str, allow_download: bool = False,
             device: str = "cpu", max_calls: int = 100) -> "LayaBackend":
        # Validate before importing an optional runtime or touching the hub.
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("an immutable checkpoint SHA is required")
        if not allow_download:
            raise ValueError("explicit download/load opt-in required")
        if device not in ("cpu", "cuda"):
            raise ValueError("device must be cpu or cuda")
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls must be positive")
        import laya
        agent = laya.load("convaiinnovations/laya", subfolder="multilingual",
                          revision=revision, device=device, fast=False, compile=False)
        if getattr(agent, "revision", None) != revision:
            raise ValueError("loaded checkpoint does not match requested revision")
        backend = cls(revision=revision, predict=agent.predict,
                      runtime_version=laya.__version__, max_calls=max_calls)
        backend.device = str(agent.device)
        return backend

    def evaluate(self, state_text: str, questions: Sequence[ReflexQuestion]) -> Mapping[str, Any]:
        self.last_usage = {}
        self.last_raw_answers = {}
        if self.calls >= self.max_calls:
            raise ValueError("call_budget_exceeded")
        names = [q.name for q in questions]
        if not names or len(set(names)) != len(names):
            raise ValueError("nonempty unique questions required")
        wire = {}
        for q in questions:
            row = {"type": q.kind.value, "instructions": q.instructions}
            if q.criteria is not None:
                row["criteria"] = q.criteria
            wire[q.name] = row
        self.calls += 1
        result = self._predict(state_text, wire, max_len=self.max_len)
        usage = result.get("usage", {})
        if not isinstance(usage, Mapping):
            raise ValueError("invalid usage")
        self.last_usage = dict(usage)
        if usage.get("truncated") or usage.get("state_tokens_dropped", 0) or usage.get("options"):
            raise ValueError("truncated state or collapsed options")
        raw = result.get("answers")
        if not isinstance(raw, Mapping) or set(raw) != set(names):
            raise ValueError("incomplete or extra answers")
        self.last_raw_answers = deepcopy(dict(raw))
        answers = normalize_systemone_answers(raw, questions, preserve_noul_confidence=True)
        ReflexEngine(InjectedReflexBackend(answers, latin_only=False)).evaluate(state_text, questions)
        return answers
