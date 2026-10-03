"""Opt-in loopback Ollama transport for advisory Tev1 decision captures.

Importing or constructing this adapter performs no I/O. Only an explicit probe
or capture calls the server; no model is pulled and no active route is changed.
Provider concentration is deliberately not passed to the calibration gate.
"""

from __future__ import annotations

import http.client
import json
import math
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass, replace
from threading import Event, Timer
from time import perf_counter, time
from typing import Any
from urllib.parse import urlsplit

from .decision_adapter import (
    REQUEST_SCHEMA_VERSION,
    DecisionCapture,
    DecisionRequest,
    capture_decision,
    replay_decision,
)
from .decision_clock import DecisionTiming, assess_decision_timing
from .reflex import ReflexKind, ReflexQuestion

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
SUPPORTED_MODELS = ("tev1:0.8b", "tev1:4b")
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_STATE_CHARS = 6000  # A size bound, not a tokenizer or context guarantee.
MAX_QUESTIONS = 64


def _positive_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("timeout_ms must be a finite number in (0, 120000].")
    if not math.isfinite(value) or not 0 < value <= 120000:
        raise ValueError("timeout_ms must be a finite number in (0, 120000].")
    return float(value)


def _origin(base_url: str) -> tuple[str, int]:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "::1")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be an HTTP origin on literal 127.0.0.1 or ::1.")
    port = 11434 if parsed.port is None else parsed.port
    if port == 0:
        raise ValueError("invalid_local_port")
    return parsed.hostname, port


def _version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?(?:[-+][A-Za-z0-9.-]+)?", value)
    if match is None:
        raise ValueError("invalid_ollama_version")
    return tuple(int(part or 0) for part in match.groups())


@dataclass(frozen=True)
class Tev1Identity:
    model: str
    model_digest: str
    ollama_version: str

    def __post_init__(self) -> None:
        if self.model not in SUPPORTED_MODELS:
            raise ValueError("Use an explicit tev1:0.8b or tev1:4b tag.")
        if not isinstance(self.model_digest, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.model_digest
        ):
            raise ValueError("invalid_model_digest")
        if not isinstance(self.ollama_version, str) or _version(self.ollama_version) < (
            0,
            35,
            0,
        ):
            raise ValueError("Ollama 0.35 or later is required.")

    @property
    def backend_id(self) -> str:
        return "ollama.systemone/" + self.model

    @property
    def backend_version(self) -> str:
        return f"ollama/{self.ollama_version};{self.model_digest}"


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _no_constant(value: str) -> Any:
    raise ValueError("non_finite_json_number")


def _remaining(deadline: float) -> float:
    seconds = deadline - perf_counter()
    if seconds <= 0:
        raise TimeoutError("decision_deadline_expired")
    return seconds


class _LocalJSONClient:
    def __init__(self, base_url: str) -> None:
        self.host, self.port = _origin(base_url)

    def request(
        self, method: str, path: str, deadline: float, body: bytes | None = None
    ) -> Any:
        # http.client neither consults proxy environment variables nor redirects.
        connection = http.client.HTTPConnection(
            self.host, self.port, timeout=_remaining(deadline)
        )
        timer = None
        guard_socket = None
        expired = Event()
        try:
            connection.connect()
            sock = connection.sock
            if sock is None:
                raise OSError("no_local_socket")
            # A response may close HTTPConnection's socket while its file still
            # owns the descriptor. A duplicate keeps shutdown available then.
            guard_socket = sock.dup()

            def interrupt() -> None:
                expired.set()
                try:
                    guard_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            # Socket timeouts alone reset on every read. Interrupt the socket at
            # the absolute deadline as well, including slowly streamed headers.
            timer = Timer(_remaining(deadline), interrupt)
            timer.daemon = True
            timer.start()
            connection.request(
                method,
                path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                if response.status >= 500:
                    raise OSError(f"local_http_{response.status}")
                raise ValueError(f"local_http_{response.status}")
            if (
                response.getheader("Content-Type", "").split(";", 1)[0].strip()
                != "application/json"
            ):
                raise ValueError("non_json_response")
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise ValueError("encoded_response_not_supported")
            length = response.getheader("Content-Length")
            if length is not None and (
                not length.isdecimal() or int(length) > MAX_RESPONSE_BYTES
            ):
                raise ValueError("response_size_exceeded")
            chunks = bytearray()
            while True:
                _remaining(deadline)
                part = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - len(chunks)))
                if not part:
                    break
                chunks.extend(part)
                if len(chunks) > MAX_RESPONSE_BYTES:
                    raise ValueError("response_size_exceeded")
            if expired.is_set():
                raise TimeoutError("decision_deadline_expired")
            _remaining(deadline)
            return json.loads(
                chunks.decode("utf-8"),
                object_pairs_hook=_no_duplicates,
                parse_constant=_no_constant,
            )
        except http.client.HTTPException as exc:
            if expired.is_set():
                raise TimeoutError("decision_deadline_expired") from exc
            raise
        finally:
            if timer is not None:
                timer.cancel()
            if guard_socket is not None:
                guard_socket.close()
            connection.close()


def _probe(client: _LocalJSONClient, model: str, deadline: float) -> Tev1Identity:
    version = client.request("GET", "/api/version", deadline)
    tags = client.request("GET", "/api/tags", deadline)
    if (
        not isinstance(version, dict)
        or not isinstance(tags, dict)
        or not isinstance(tags.get("models"), list)
    ):
        raise TypeError("invalid_runtime_metadata")
    matches = [
        entry
        for entry in tags["models"]
        if isinstance(entry, dict) and entry.get("name") == model
    ]
    if len(matches) != 1:
        raise ValueError("model_not_installed_or_ambiguous")
    digest = matches[0].get("digest")
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = "sha256:" + digest
    return Tev1Identity(model, digest, version.get("version"))


def probe_tev1_model(
    *, model: str, base_url: str = DEFAULT_BASE_URL, timeout_ms: float = 5000
) -> Tev1Identity:
    """Explicitly inspect an already installed model; never download it."""
    if model not in SUPPORTED_MODELS:
        raise ValueError("Use an explicit tev1:0.8b or tev1:4b tag.")
    timeout = _positive_timeout(timeout_ms)
    return _probe(_LocalJSONClient(base_url), model, perf_counter() + timeout / 1000)


def _probabilities(raw: Any, keys: tuple[str, ...]) -> dict[str, float]:
    if not isinstance(raw, dict) or set(raw) != set(keys):
        raise ValueError("probability_keys_mismatch")
    result = {key: _number(raw[key], 1) for key in keys}
    if abs(sum(result.values()) - 1) > 1e-6:
        raise ValueError("probabilities_do_not_sum_to_one")
    return result


def _number(value: Any, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("invalid_answer_number")
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("invalid_answer_number")
    return float(value)


class OllamaTev1Transport:
    """Bounded, explicitly invoked transport. Captures stay advisory.

    Runtime version and model digest are checked before and after inference.
    These five local requests share one deadline. A pinned tag must still not
    be mutated concurrently: the server API does not provide an atomic lease.
    """

    def __init__(
        self,
        identity: Tev1Identity,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_ms: float = 5000,
    ) -> None:
        if not isinstance(identity, Tev1Identity):
            raise TypeError("identity must be a Tev1Identity.")
        self.identity = identity
        self.timeout_ms = _positive_timeout(timeout_ms)
        self._client = _LocalJSONClient(base_url)

    def _wire(
        self, payload: Mapping[str, Any]
    ) -> tuple[bytes, tuple[ReflexQuestion, ...]]:
        fields = {
            "schema_version",
            "request_id",
            "state",
            "state_age_ms",
            "questions",
            "backend",
        }
        if (
            not isinstance(payload, Mapping)
            or set(payload) != fields
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != REQUEST_SCHEMA_VERSION
        ):
            raise ValueError("invalid_decision_envelope")
        if payload["backend"] != {
            "backend_id": self.identity.backend_id,
            "backend_version": self.identity.backend_version,
        }:
            raise ValueError("unpinned_or_mismatched_backend")
        state = payload["state"]
        if not isinstance(state, str) or len(state) > MAX_STATE_CHARS:
            raise ValueError("state_size_exceeded")
        items = payload["questions"]
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_QUESTIONS:
            raise ValueError("question_count_exceeded")
        questions = []
        wire = {}
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                "name",
                "kind",
                "instructions",
                "criteria",
            }:
                raise ValueError("invalid_question_envelope")
            question = ReflexQuestion(
                item["name"],
                ReflexKind(item["kind"]),
                item["instructions"],
                item["criteria"],
            )
            if question.name != question.name.strip() or question.name in wire:
                raise ValueError("duplicate_or_untrimmed_question")
            if question.kind == ReflexKind.SCORE:
                levels = question.option_keys
                if (
                    len(levels) > 20
                    or len(set(levels)) != len(levels)
                    or any(not level.strip() for level in levels)
                ):
                    raise ValueError("invalid_score_levels")
            if (
                question.kind == ReflexKind.NOUL
                and question.criteria is not None
                and set(question.criteria) != {"true", "false"}
            ):
                raise ValueError("invalid_noul_criteria")
            if question.criteria is not None and any(
                not isinstance(value, str)
                for value in (
                    question.criteria.values()
                    if isinstance(question.criteria, Mapping)
                    else question.criteria
                )
            ):
                raise ValueError("invalid_criteria_description")
            wire[question.name] = {
                "type": question.kind.value,
                "instructions": question.instructions,
                "criteria": question.criteria,
            }
            questions.append(question)
        body = json.dumps(
            {"model": self.identity.model, "state": state, "questions": wire},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise ValueError("request_size_exceeded")
        return body, tuple(questions)

    def _normalize(
        self, response: Any, questions: tuple[ReflexQuestion, ...]
    ) -> dict[str, Any]:
        if not isinstance(response, dict) or set(response) - {
            "model",
            "answers",
            "usage",
        }:
            raise ValueError("invalid_response_envelope")
        if response.get("model") != self.identity.model:
            raise ValueError("response_model_mismatch")
        answers = response.get("answers")
        if not isinstance(answers, dict) or set(answers) != {
            question.name for question in questions
        }:
            raise ValueError("missing_or_unknown_answer")
        normalized = {}
        for question in questions:
            raw = answers[question.name]
            if not isinstance(raw, dict) or raw.get("type") != question.kind.value:
                raise ValueError("answer_type_mismatch")
            if question.kind == ReflexKind.NOUL:
                if set(raw) != {"type", "noul"}:
                    raise ValueError("invalid_noul_fields")
                noul = _number(raw["noul"], 1)
                normalized[question.name] = {
                    "noul": noul,
                    "probabilities": {"false": 1 - noul, "true": noul},
                    "confidence": None,
                }
                continue
            expected = {"type", "probabilities", "confidence"} | (
                {"choice"}
                if question.kind == ReflexKind.CHOICE
                else {"score", "legend"}
            )
            if set(raw) != expected:
                raise ValueError("invalid_answer_fields")
            _number(
                raw["confidence"], 1
            )  # Validate then discard uncalibrated concentration.
            keys = question.option_keys
            if question.kind == ReflexKind.CHOICE:
                probabilities = _probabilities(raw["probabilities"], keys)
                choice = raw["choice"]
                if (
                    not isinstance(choice, str)
                    or choice not in keys
                    or probabilities[choice] < max(probabilities.values()) - 1e-6
                ):
                    raise ValueError("invalid_choice")
                normalized[question.name] = {
                    "choice": choice,
                    "probabilities": probabilities,
                    "confidence": None,
                }
            else:
                indices = tuple(str(index) for index in range(len(keys)))
                if raw["legend"] != dict(zip(indices, keys)):
                    raise ValueError("score_legend_mismatch")
                probabilities = _probabilities(raw["probabilities"], indices)
                score = _number(raw["score"], len(keys) - 1)
                if (
                    abs(
                        score
                        - sum(
                            index * probabilities[str(index)]
                            for index in range(len(keys))
                        )
                    )
                    > 1e-6
                ):
                    raise ValueError("score_probability_mismatch")
                normalized[question.name] = {
                    "score": score,
                    "probabilities": dict(zip(keys, probabilities.values())),
                    "confidence": None,
                }
        usage = response.get("usage", {})
        if not isinstance(usage, dict) or set(usage) - {
            "input_tokens",
            "output_tokens",
        }:
            raise ValueError("invalid_usage")
        if any(type(value) is not int or value < 0 for value in usage.values()):
            raise ValueError("invalid_usage")
        return {
            "answers": normalized,
            "usage": {key + "_total": value for key, value in usage.items()},
        }

    def _call(self, payload: Mapping[str, Any], deadline: float) -> dict[str, Any]:
        body, questions = self._wire(payload)
        if _probe(self._client, self.identity.model, deadline) != self.identity:
            raise ValueError("runtime_identity_changed")
        response = self._client.request("POST", "/v1/systemone", deadline, body)
        if _probe(self._client, self.identity.model, deadline) != self.identity:
            raise ValueError("runtime_identity_changed")
        return self._normalize(response, questions)

    def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        result = self._call(payload, started + self.timeout_ms / 1000)
        result["usage"]["latency_ms"] = (perf_counter() - started) * 1000
        return result

    def capture(self, request: DecisionRequest) -> DecisionCapture:
        """Capture once with measured timing; never grant auto-act or retry."""
        if not isinstance(request, DecisionRequest) or request.budget is None:
            raise ValueError(
                "a timed Tev1 capture requires a DecisionRequest with a budget."
            )
        if (request.backend_id, request.backend_version) != (
            self.identity.backend_id,
            self.identity.backend_version,
        ):
            raise ValueError("unpinned_or_mismatched_backend")
        initial = assess_decision_timing(
            request.budget, DecisionTiming(0, request.state_age_ms)
        )
        if not initial.usable:
            return DecisionCapture("error", initial.reason_code, request)
        started = perf_counter()
        deadline = started + min(self.timeout_ms, request.budget.budget_ms) / 1000
        capture = capture_decision(
            request,
            backend_id=self.identity.backend_id,
            backend_version=self.identity.backend_version,
            transport=lambda payload: self._call(payload, deadline),
            captured_at_ms=time() * 1000,
        )
        if not capture.performed:
            return capture
        elapsed_ms = (perf_counter() - started) * 1000
        record = replace(
            capture.record, usage={**capture.record.usage, "latency_ms": elapsed_ms}
        )
        age = (
            None if request.state_age_ms is None else request.state_age_ms + elapsed_ms
        )
        replay = replay_decision(
            record, request, timing=DecisionTiming(elapsed_ms, age)
        )
        return replace(capture, record=record, replay=replay)
