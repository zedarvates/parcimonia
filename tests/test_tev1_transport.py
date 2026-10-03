import copy
import json
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from time import perf_counter

import pytest

from tiberium_ai.decision_adapter import (
    DecisionRequest,
    read_decision_record,
    replay_decision,
    write_decision_record,
)
from tiberium_ai.decision_clock import DecisionBudget
from tiberium_ai.reflex import CalibrationSnapshot, ReflexKind, ReflexQuestion
from tiberium_ai.tev1_transport import (
    MAX_RESPONSE_BYTES,
    OllamaTev1Transport,
    Tev1Identity,
    probe_tev1_model,
)

IDENTITY = Tev1Identity("tev1:0.8b", "sha256:" + "a" * 64, "0.35.0")
QUESTIONS = (
    ReflexQuestion(
        "intent",
        ReflexKind.CHOICE,
        "Quelle intention ?",
        {"document": "Document", "none": "Aucune"},
    ),
    ReflexQuestion("done", ReflexKind.NOUL, "Vérifié ?"),
    ReflexQuestion(
        "pressure",
        ReflexKind.SCORE,
        "Quelle pression ?",
        ["Faible", "Moyenne", "Forte"],
    ),
)
RESPONSE = {
    "model": "tev1:0.8b",
    "answers": {
        "intent": {
            "type": "choice",
            "choice": "document",
            "probabilities": {"document": 0.8, "none": 0.2},
            "confidence": 0.99,
        },
        "done": {"type": "noul", "noul": 0.7},
        "pressure": {
            "type": "score",
            "score": 1.4,
            "legend": {"0": "Faible", "1": "Moyenne", "2": "Forte"},
            "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5},
            "confidence": 0.99,
        },
    },
    "usage": {"input_tokens": 123, "output_tokens": 3},
}


def request(**kwargs):
    return DecisionRequest(
        "req-fr",
        "État français.",
        QUESTIONS,
        backend_id=IDENTITY.backend_id,
        backend_version=IDENTITY.backend_version,
        state_age_ms=0,
        budget=kwargs.pop("budget", DecisionBudget(2000, 10000, "rules")),
        **kwargs,
    )


@contextmanager
def server(
    *,
    response=None,
    status=200,
    raw=None,
    delay=0,
    drift=False,
    content_type="application/json",
    slow_headers=False,
    model_identity=IDENTITY,
):
    calls = []
    tags_read = 0

    class Handler(BaseHTTPRequestHandler):
        # Exercise Connection: close too: the absolute deadline must still work.
        protocol_version = "HTTP/1.0"

        def log_message(self, *_):
            pass

        def do_GET(self):
            nonlocal tags_read
            calls.append(("GET", self.path, None))
            if self.path == "/api/version":
                self.send_json({"version": model_identity.ollama_version})
            elif self.path == "/api/tags":
                tags_read += 1
                digest = "b" * 64 if drift and tags_read > 1 else "a" * 64
                self.send_json(
                    {"models": [{"name": model_identity.model, "digest": digest}]}
                )
            else:
                self.send_error(404)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("POST", self.path, payload))
            if slow_headers:
                self.wfile.write(b"HTTP/1.0 200 OK\r\n")
                self.wfile.flush()
                Event().wait(delay)
                return
            value = (
                RESPONSE
                if response is None
                else response(payload)
                if callable(response)
                else response
            )
            body = raw if raw is not None else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Location", "http://example.invalid/forbidden")
            self.end_headers()
            Event().wait(delay)
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def send_json(self, value):
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=1)


def test_probe_reads_installed_digest_without_pulling():
    with server() as (url, calls):
        identity = probe_tev1_model(model="tev1:0.8b", base_url=url)
    assert identity == IDENTITY
    assert [call[1] for call in calls] == ["/api/version", "/api/tags"]


def test_live_http_stub_round_trip_preserves_provenance_and_offline_replay(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:1")
    with server() as (url, calls):
        transport = OllamaTev1Transport(IDENTITY, base_url=url)
        assert calls == []  # Construction is inert.
        capture = transport.capture(request())
    assert capture.usable and capture.record.data_origin == "recorded"
    assert capture.record.backend_version == IDENTITY.backend_version
    assert len(calls) == 5
    sent = next(call[2] for call in calls if call[0] == "POST")
    assert set(sent) == {"model", "state", "questions"}
    assert sent["state"] == "État français."
    assert sent["questions"]["pressure"]["criteria"] == ["Faible", "Moyenne", "Forte"]
    record = capture.record
    assert record.answers["pressure"]["probabilities"] == {
        "Faible": 0.1,
        "Moyenne": 0.4,
        "Forte": 0.5,
    }
    assert record.answers["done"]["noul"] == 0.7
    assert record.usage["input_tokens_total"] == 123 and record.usage["latency_ms"] > 0
    path = tmp_path / "capture.json"
    write_decision_record(path, record)
    replay = replay_decision(
        read_decision_record(path), request()
    )  # Server has stopped.
    assert replay.performed
    assert replay.batch.get("pressure").score == 1.4
    calibration = CalibrationSnapshot(
        "test",
        True,
        100,
        coverage_at_threshold=1,
        accuracy_at_threshold=1,
        data_origin="labelled_outcomes",
    )
    calibrated = replay_decision(record, request(), calibration=calibration)
    assert all(
        answer.confidence is None and not answer.auto_act_allowed
        for answer in calibrated.batch.answers
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434",
        "http://localhost:11434",
        "http://example.com",
        "http://127.0.0.1.evil",
        "http://user:secret@127.0.0.1",
        "http://127.0.0.1/path",
        "http://127.0.0.1?x=1",
        "http://127.0.0.1#fragment",
    ],
)
def test_remote_origins_and_ambiguous_urls_are_refused(url):
    with pytest.raises(ValueError):
        OllamaTev1Transport(IDENTITY, base_url=url)


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan"), 120001])
def test_unbounded_or_invalid_timeout_is_refused(timeout):
    with pytest.raises((ValueError, TypeError)):
        OllamaTev1Transport(IDENTITY, timeout_ms=timeout)


@pytest.mark.parametrize(
    "identity",
    [
        ("tev1", "sha256:" + "a" * 64, "0.35.0"),
        ("tev1:4b", "latest", "0.35.0"),
        ("tev1:0.8b", "sha256:" + "a" * 64, "0.34.9"),
    ],
)
def test_identity_requires_explicit_tag_digest_and_supported_runtime(identity):
    with pytest.raises(ValueError):
        Tev1Identity(*identity)


def test_missing_usage_stays_unknown():
    response = copy.deepcopy(RESPONSE)
    del response["usage"]
    with server(response=response) as (url, _):
        capture = OllamaTev1Transport(IDENTITY, base_url=url).capture(request())
    assert capture.performed
    assert set(capture.record.usage) == {"latency_ms"}


@pytest.mark.parametrize("model", ["tev1:0.8b", "tev1:4b"])
def test_both_explicit_model_sizes_use_the_same_contract(model):
    identity = replace(IDENTITY, model=model)
    response = copy.deepcopy(RESPONSE)
    response["model"] = model
    pinned = replace(
        request(),
        backend_id=identity.backend_id,
        backend_version=identity.backend_version,
    )
    with server(response=response, model_identity=identity) as (url, _):
        capture = OllamaTev1Transport(identity, base_url=url).capture(pinned)
    assert capture.usable and capture.record.backend_id == identity.backend_id


def test_model_identity_drift_discards_the_answer():
    with server(drift=True) as (url, _):
        capture = OllamaTev1Transport(IDENTITY, base_url=url).capture(request())
    assert capture.status == "error" and capture.record is None


def bad_response(path, value):
    result = copy.deepcopy(RESPONSE)
    target = result
    for key in path[:-1]:
        target = target[key]
    if value == "__delete__":
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return result


@pytest.mark.parametrize(
    "response",
    [
        bad_response(("model",), "tev1:4b"),
        bad_response(("answers", "done"), "__delete__"),
        bad_response(("answers", "done", "type"), "choice"),
        bad_response(("answers", "done", "noul"), True),
        bad_response(("answers", "done", "noul"), 1.1),
        bad_response(("answers", "intent", "choice"), "missing"),
        bad_response(("answers", "intent", "choice"), "none"),
        bad_response(("answers", "intent", "probabilities"), {"document": 0.8}),
        bad_response(
            ("answers", "intent", "probabilities"), {"document": 0.8, "none": 0.3}
        ),
        bad_response(("answers", "intent", "confidence"), float("nan")),
        bad_response(
            ("answers", "pressure", "legend"),
            {"0": "Forte", "1": "Moyenne", "2": "Faible"},
        ),
        bad_response(("answers", "pressure", "score"), 0.2),
        bad_response(("answers", "pressure", "score"), 5),
        bad_response(("usage", "input_tokens"), True),
        bad_response(("usage", "cost"), 0),
        bad_response(("answers", "invented"), {"type": "noul", "noul": 1}),
    ],
)
def test_malformed_or_inconsistent_answers_never_produce_a_record(response):
    with server(response=response) as (url, _):
        capture = OllamaTev1Transport(IDENTITY, base_url=url).capture(request())
    assert capture.status == "error" and capture.record is None


@pytest.mark.parametrize(
    "raw",
    [
        b'{"model":"tev1:0.8b","model":"tev1:4b"}',
        b"not JSON",
        b"\xff",
        b'{"value":Infinity}',
        b"x" * (MAX_RESPONSE_BYTES + 1),
    ],
)
def test_invalid_duplicate_nonfinite_or_oversized_json_is_refused(raw):
    with server(raw=raw) as (url, _):
        capture = OllamaTev1Transport(IDENTITY, base_url=url).capture(request())
    assert capture.status == "error" and capture.record is None


@pytest.mark.parametrize(
    "status,expected", [(302, "error"), (404, "error"), (500, "unavailable")]
)
def test_no_redirect_retry_or_silent_default(status, expected):
    with server(status=status) as (url, calls):
        capture = OllamaTev1Transport(IDENTITY, base_url=url).capture(request())
    assert capture.status == expected
    assert sum(call[0] == "POST" for call in calls) == 1
    assert len(calls) == 3


@pytest.mark.parametrize("slow_headers", [False, True])
def test_absolute_deadline_interrupts_body_and_headers(slow_headers):
    with server(delay=0.6, slow_headers=slow_headers) as (url, _):
        started = perf_counter()
        capture = OllamaTev1Transport(IDENTITY, base_url=url).capture(
            request(budget=DecisionBudget(150, 10000, "rules"))
        )
        elapsed = perf_counter() - started
    assert elapsed < 0.5
    assert not capture.performed and capture.record is None


def test_late_state_cannot_be_used_even_when_the_http_call_succeeds():
    with server() as (url, _):
        capture = OllamaTev1Transport(IDENTITY, base_url=url).capture(
            request(budget=DecisionBudget(2000, 0, "rules"))
        )
    assert capture.performed and not capture.usable
    assert capture.replay.timing.reason_code == "state_age_exceeds_bound"
    assert capture.replay.timing.fallback_route_id == "rules"


def test_unknown_age_and_zero_budget_do_not_call_the_server():
    with server() as (url, calls):
        transport = OllamaTev1Transport(IDENTITY, base_url=url)
        unknown = transport.capture(replace(request(), state_age_ms=None))
        zero = transport.capture(request(budget=DecisionBudget(0, 10000, "rules")))
    assert unknown.detail_code == "state_age_unknown" and not unknown.performed
    assert not zero.performed
    assert calls == []


@pytest.mark.parametrize(
    "changed",
    [
        {"state": "a" * 6001},
        {
            "questions": tuple(
                ReflexQuestion(f"q-{index}", ReflexKind.NOUL, "Question ?")
                for index in range(65)
            )
        },
        {
            "questions": (
                ReflexQuestion(
                    "big", ReflexKind.CHOICE, "a" * 66000, {"a": "A", "b": "B"}
                ),
            )
        },
        {
            "questions": (
                ReflexQuestion(
                    "duplicates", ReflexKind.SCORE, "Question ?", ["same", "same"]
                ),
            )
        },
    ],
)
def test_size_and_shape_failures_are_checked_before_network_io(changed):
    with server() as (url, calls):
        capture = OllamaTev1Transport(IDENTITY, base_url=url).capture(
            replace(request(), **changed)
        )
    assert not capture.performed and calls == []


def test_request_identity_cannot_be_relabelled():
    transport = OllamaTev1Transport(IDENTITY)
    with pytest.raises(ValueError):
        transport.capture(replace(request(), backend_version="unrelated"))
