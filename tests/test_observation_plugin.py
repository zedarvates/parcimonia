"""Exercise observation review through the isolated packaged MCP process."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "parcimonia-local"


def fixture_request():
    requirement = {"id": "connected", "source_id": "authored-server",
                   "source_revision": "build-1", "input_sha256": "a" * 64,
                   "verifier_id": "authored-connection", "verifier_version": "1",
                   "max_age_seconds": 60}
    observation = {key: value for key, value in requirement.items()
                   if key not in ("id", "max_age_seconds")}
    observation.update(id="current", requirement_id="connected", task_id="reconnect",
                       task_revision="attempt-1", observed_at=time.time() - 2, outcome="pass")
    return {"task_id": "reconnect", "task_revision": "attempt-1",
            "requirements": [requirement], "observations": [observation],
            "probes": [{"id": "read-server", "requirement_ids": ["connected"],
                        "estimated_latency_ms": None}]}


def exchange(calls, cwd):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "authored-test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    messages.extend({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                     "params": {"name": "parcimonia_local_observations", "arguments": args}}
                    for index, args in enumerate(calls, 3))
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(PLUGIN / "server.py")], cwd=cwd,
        input="".join(json.dumps(message) + "\n" for message in messages),
        capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
    assert completed.stderr == ""
    replies = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2, *range(3, 3 + len(calls))]
    return replies


def test_packaged_transport_discovers_and_reviews_current_stale_and_failed_reports(tmp_path):
    current = fixture_request()
    stale = deepcopy(current)
    stale["observations"][0]["observed_at"] = 0
    failed = deepcopy(current)
    failed["observations"].append({**failed["observations"][0], "id": "failure",
                                   "observed_at": time.time() - 1, "outcome": "fail"})
    replies = exchange([{"request": value} for value in (current, stale, failed)], tmp_path)
    assert replies[0]["result"]["serverInfo"]["version"] == "0.4.3"
    tools = {tool["name"]: tool for tool in replies[1]["result"]["tools"]}
    assert set(tools) == {"parcimonia_local_plan", "parcimonia_local_hardware",
                          "parcimonia_local_context", "parcimonia_local_observations"}
    schema = tools["parcimonia_local_observations"]["inputSchema"]
    assert schema["required"] == ["request"]
    assert schema["additionalProperties"] is False
    results = [reply["result"]["structuredContent"] for reply in replies[2:]]
    assert [result["status"] for result in results] == ["ready", "needs_observation", "blocked"]
    assert results[1]["next_probe"]["id"] == "read-server"
    assert results[1]["next_probe"]["estimated_latency_ms"] is None
    assert results[2]["requirements"][0]["observation_ids"] == ["failure"]
    for result in results:
        assert result["auto_act_allowed"] is False
        assert result["evidence_trust"] == "host_reported_not_independently_attested"


@pytest.mark.parametrize("change", ["wrong_revision", "conflict", "boolean_time", "extra_action"])
def test_packaged_tool_preserves_negative_evidence_and_survives_invalid_calls(tmp_path, change):
    value = fixture_request()
    if change == "wrong_revision":
        value["observations"][0]["task_revision"] = "another-attempt"
    elif change == "conflict":
        value["observations"].append({**value["observations"][0], "id": "contradiction",
                                      "outcome": "fail"})
    elif change == "boolean_time":
        value["observations"][0]["observed_at"] = True
    else:
        value["execute"] = "untrusted data, never execute"
    replies = exchange([{"request": value}, {"request": fixture_request()}], tmp_path)
    result = replies[2]["result"]
    if change in ("boolean_time", "extra_action"):
        assert result["isError"] is True
    else:
        report = result["structuredContent"]
        assert report["status"] == "needs_observation"
        assert report["requirements"][0]["state"] == (
            "missing" if change == "wrong_revision" else "conflict")
    assert replies[3]["result"]["structuredContent"]["status"] == "ready"


def test_observation_code_and_package_inventory_match():
    source = ROOT / "src" / "tiberium_ai" / "observation_review.py"
    vendored = PLUGIN / "_vendor" / "observation_review.py"
    assert source.read_bytes() == vendored.read_bytes()
    sources = json.loads((PLUGIN / "SOURCES.json").read_text())
    assert sources["_vendor/observation_review.py"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    inventory = json.loads((PLUGIN / "FILES.json").read_text())["files"]
    for name, digest in inventory.items():
        assert hashlib.sha256((PLUGIN / name).read_bytes()).hexdigest() == digest, name
    actual = {str(path.relative_to(PLUGIN)).replace("\\", "/") for path in PLUGIN.rglob("*")
              if path.is_file() and "__pycache__" not in path.parts}
    assert actual == set(inventory) | {"FILES.json"}
