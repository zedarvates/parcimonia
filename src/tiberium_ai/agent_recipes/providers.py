"""Optional TypeSafe HTTP transport. Construction never calls the network."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..reflex import InjectedReflexBackend, ReflexEngine, ReflexQuestion
from ..provider_answers import NORMALIZER_VERSION, normalize_systemone_answers
from .core import canonical


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _post(payload: Mapping[str, Any], key: str, timeout: float) -> Mapping[str, Any]:
    request = Request("https://api.typesafe.ai/v1/systemone",
                      data=canonical(payload).encode("utf-8"), method="POST",
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            data = response.read(2097153)
            if len(data) > 2097152:
                raise ValueError("oversized provider response")
            return json.loads(data)
    except Exception:
        raise OSError("TypeSafe transport failed; no automatic retry") from None


class TypeSafeBackend:
    """HTTP API https://docs.typesafe.ai/api, checked 2026-10-02.

    Real access requires explicit allow_network, API key, pinned model and call cap.
    Token usage is observed; billed monetary cost remains unknown.
    Inject post for offline transport contract tests.
    """
    latin_only = False
    backend_id = "typesafe.http@1"

    def __init__(self, *, api_key: str, model: str, allow_network: bool = False,
                 max_calls: int = 1, timeout: float = 5,
                 post: Callable[..., Mapping[str, Any]] | None = None) -> None:
        if not api_key or not model or model.endswith("latest"):
            raise ValueError("key and pinned model version required")
        if type(max_calls) is not int or max_calls < 1 or not 0 < timeout <= 60:
            raise ValueError("invalid transport bounds")
        self._key = api_key
        self.model, self.allow_network = model, allow_network
        self.max_calls, self.timeout = max_calls, timeout
        self._post = post
        self.calls = 0
        self.last_usage: dict[str, Any] = {}
        self.last_model: str | None = None
        self.last_raw_answers: dict[str, Any] = {}

    @property
    def backend_version(self) -> str:
        return f"{self.model}|{NORMALIZER_VERSION}"

    def evaluate(self, state_text: str, questions: Sequence[ReflexQuestion]) -> Mapping[str, Any]:
        self.last_usage, self.last_model = {}, None
        self.last_raw_answers = {}
        if self._post is None and not self.allow_network:
            raise ValueError("network_not_authorized")
        if self.calls >= self.max_calls:
            raise ValueError("call_budget_exceeded")
        wire = {}
        for q in questions:
            row = {"type": q.kind.value, "instructions": q.instructions}
            if q.criteria is not None:
                row["criteria"] = q.criteria
            wire[q.name] = row
        self.calls += 1
        payload = (self._post or _post)({"state": state_text, "model": self.model,
                                      "questions": wire}, self._key, self.timeout)
        if payload.get("model") != self.model:
            raise ValueError("provider model does not match pinned identity")
        self.last_model = payload["model"]
        usage = payload.get("usage")
        if not isinstance(usage, Mapping):
            raise ValueError("missing provider usage")
        for k in ("input_tokens", "output_tokens"):
            if usage.get(k) is not None and (type(usage[k]) is not int or usage[k] < 0):
                raise ValueError("invalid provider token count")
        self.last_usage = {"input_tokens": usage.get("input_tokens"),
                           "output_tokens": usage.get("output_tokens"), "billed_cost": None}
        if usage.get("truncated") or usage.get("state_tokens_dropped", 0) or usage.get("options"):
            raise ValueError("truncated state or collapsed options")
        raw = payload.get("answers")
        if not isinstance(raw, Mapping) or set(raw) != {q.name for q in questions}:
            raise ValueError("incomplete or extra provider answers")
        self.last_raw_answers = deepcopy(dict(raw))
        answers = normalize_systemone_answers(raw, questions)
        ReflexEngine(InjectedReflexBackend(answers, latin_only=False)).evaluate(state_text, questions)
        return answers
