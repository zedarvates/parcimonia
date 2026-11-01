"""Offline behavior checks; HTTP fixtures are not model-quality measurements."""
import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from collections import Counter
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tiberium_ai import local_text_eval as ev


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "examples/fixtures/local_text_cases_fr.json"
ORIGIN = "http://127.0.0.1:1234"


def response(case, **changes):
    value = {
        "kind": "local_completion", "schema_version": 1, "origin": ORIGIN,
        "requested_model": "test-model", "response_model": "test-model",
        "status": "completed", "content": json.dumps(case["expected"], ensure_ascii=False),
        "finish_reason": "stop", "http_status": 200, "error_type": None,
        "latency_ms": 3.0,
        "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        "inference_attempted": True, "execution_performed": False, "retries": 0,
    }
    value.update(changes)
    return value


@contextmanager
def fake_runtime(corpus, overrides=None):
    calls = []
    overrides = overrides or {}

    def completion(**kwargs):
        index = len(calls)
        calls.append(kwargs)
        return response(corpus["cases"][index], **overrides.get(index, {}))

    probe = {"status": "reachable", "model_ids": ["test-model"], "origin": ORIGIN,
             "loaded_state": "not_observed", "inference_ready": None}
    with patch.object(ev, "probe_models", return_value=probe), patch.object(
        ev, "chat_completion", side_effect=completion,
    ):
        yield calls


class LocalTextEvalTests(unittest.TestCase):
    def setUp(self):
        self.corpus = ev.load_corpus(CORPUS)
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name) / "run"
        self.addCleanup(self.temp.cleanup)

    def capture(self, **kwargs):
        return ev.capture(self.corpus, self.out, model="test-model",
                          resources_checked=True, **kwargs)

    def test_authored_corpus_has_24_distinct_cases(self):
        self.assertEqual(len(self.corpus["cases"]), 24)
        self.assertEqual(len({c["id"] for c in self.corpus["cases"]}), 24)
        self.assertEqual(Counter(c["family"] for c in self.corpus["cases"]),
                         {"tools": 8, "rag": 8, "json": 4, "limits": 4})

    def test_expected_oracle_is_never_in_model_request(self):
        case = copy.deepcopy(self.corpus["cases"][0])
        case["expected"]["value"] = "ORACLE_ONLY_DO_NOT_LEAK"
        self.assertNotIn("ORACLE_ONLY_DO_NOT_LEAK", json.dumps(ev.messages_for(case)))

    def test_reference_documents_are_supplied_as_data(self):
        messages = ev.messages_for(self.corpus["cases"][14])
        self.assertTrue(any(m["role"] == "system" for m in messages))
        self.assertIn("src-15", json.dumps(messages))
        self.assertTrue(all(m["role"] in {"system", "user"} for m in messages))

    def test_every_authored_oracle_passes_its_case(self):
        for case in self.corpus["cases"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(ev.grade_case(case, response(case))["pass"])

    def test_strict_json_rejects_duplicates_nonfinite_and_fences(self):
        case = self.corpus["cases"][8]
        for content in ('{"status":"answer","status":"abstain"}',
                        '{"value":NaN}', '```json\n{}\n```', '<think>x</think>{}'):
            with self.subTest(content=content):
                grade = ev.grade_case(case, response(case, content=content))
                self.assertFalse(grade["pass"])
                self.assertFalse(grade["json_valid"])

    def test_json_valid_but_false_value_and_false_citation_fail(self):
        case = self.corpus["cases"][8]
        for key, value in (("value", 4), ("sources", ["invented-source"])):
            candidate = copy.deepcopy(case["expected"])
            candidate[key] = value
            grade = ev.grade_case(case, response(case, content=json.dumps(candidate)))
            self.assertTrue(grade["json_valid"])
            self.assertFalse(grade["pass"])

    def test_python_bool_is_not_an_integer_oracle(self):
        case = copy.deepcopy(self.corpus["cases"][8])
        case["expected"]["value"] = 1
        candidate = copy.deepcopy(case["expected"])
        candidate["value"] = True
        self.assertFalse(ev.grade_case(case, response(case, content=json.dumps(candidate)))["pass"])

    def test_truncated_output_never_passes_even_when_expected_json_is_present(self):
        case = self.corpus["cases"][20]
        self.assertFalse(ev.grade_case(case, response(case, status="truncated", finish_reason="length"))["pass"])

    def test_resource_admission_is_required_before_network(self):
        with patch.object(ev, "probe_models") as probe, patch.object(ev, "chat_completion") as call:
            with self.assertRaises(ValueError):
                ev.capture(self.corpus, self.out, model="test-model")
            probe.assert_not_called()
            call.assert_not_called()

    def test_success_preserves_unknown_usage_and_does_not_select_a_model(self):
        with fake_runtime(self.corpus) as calls:
            report = self.capture()
        self.assertEqual(len(calls), 24)
        self.assertEqual(report["case_count"], 24)
        self.assertEqual(report["passed"], 24)
        self.assertEqual(report["not_attempted"], 0)
        self.assertIsNone(report["tokens"]["total_tokens"])
        self.assertFalse(report["identity_certified"])
        self.assertFalse(report["saving_claim"])
        self.assertFalse(report["auto_act_allowed"])
        self.assertIsNone(report["selected_model"])

    def test_stops_after_transport_failure_and_keeps_all_cases(self):
        with fake_runtime(self.corpus, {2: {"status": "timeout", "error_type": "timeout",
                                           "content": None, "finish_reason": None}}) as calls:
            report = self.capture()
        self.assertEqual(len(calls), 3)
        self.assertEqual(report["attempted"], 3)
        self.assertEqual(report["passed"], 2)
        self.assertEqual(report["not_attempted"], 21)
        self.assertEqual(len(report["cases"]), 24)

    def test_wrong_json_is_measured_without_stopping_the_quality_lot(self):
        with fake_runtime(self.corpus, {0: {"content": "not json"}}) as calls:
            report = self.capture()
        self.assertEqual(len(calls), 24)
        self.assertEqual(report["passed"], 23)

    def test_changed_response_identity_stops_lot(self):
        with fake_runtime(self.corpus, {0: {"response_model": "other-model"}}) as calls:
            report = self.capture()
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["not_attempted"], 23)

    def test_native_tool_calls_remain_unsupported(self):
        with fake_runtime(self.corpus, {0: {"status": "unsupported_output",
                                           "error_type": "tool_calls_not_supported",
                                           "content": None}}) as calls:
            report = self.capture()
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["passed"], 0)

    def test_existing_destination_is_never_overwritten(self):
        self.out.mkdir()
        guard = self.out / "guard.txt"
        guard.write_text("preserve")
        with fake_runtime(self.corpus) as calls:
            with self.assertRaises((FileExistsError, ValueError)):
                self.capture()
        self.assertEqual(calls, [])
        self.assertEqual(guard.read_text(), "preserve")

    def test_replay_is_offline_and_ignores_precomputed_report(self):
        with fake_runtime(self.corpus):
            expected = self.capture()
        (self.out / "report.json").write_text('{"passed":99999}')
        with patch.object(ev, "chat_completion", side_effect=AssertionError("network")), patch.object(
            ev, "probe_models", side_effect=AssertionError("network"),
        ):
            actual = ev.replay(self.corpus, self.out)
        self.assertEqual(actual, expected)

    def test_replay_rejects_modified_response_bytes(self):
        with fake_runtime(self.corpus):
            self.capture()
        record = next((self.out / "records").glob("*.json"))
        record.write_text(record.read_text() + " ")
        with self.assertRaises(ValueError):
            ev.replay(self.corpus, self.out)

    def test_replay_rejects_changed_corpus(self):
        with fake_runtime(self.corpus):
            self.capture()
        changed = copy.deepcopy(self.corpus)
        changed["cases"][0]["prompt"] += " changed"
        with self.assertRaises(ValueError):
            ev.replay(changed, self.out)

    def test_replay_rejects_unfinished_manifest(self):
        with fake_runtime(self.corpus):
            self.capture()
        path = self.out / "run.json"
        manifest = json.loads(path.read_text())
        manifest["phase"] = "capturing"
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            ev.replay(self.corpus, self.out)

    def test_plan_cli_is_offline(self):
        result = subprocess.run([sys.executable, str(ROOT / "examples/local_text_eval.py"),
                                 "plan", "--corpus", str(CORPUS)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["case_count"], 24)

    def test_real_http_truncation_stops_after_exactly_one_post(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send_json(self, value):
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                calls.append(("GET", self.path))
                self.send_json({"data": [{"id": "test-model"}]})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(("POST", self.path))
                self.send_json({"model": payload["model"], "choices": [{
                    "message": {"role": "assistant", "content": "partial"},
                    "finish_reason": "length",
                }]})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = self.capture(base_url=f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertEqual(calls, [("GET", "/v1/models"), ("POST", "/v1/chat/completions")])
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["not_attempted"], 23)
        self.assertEqual(report["passed"], 0)

    def test_expired_budget_during_manifest_sync_never_starts_post(self):
        clock = [0.0]
        write_manifest = ev._manifest

        def delayed_manifest(path, value):
            if any(c["status"] == "in_progress" for c in value["cases"]):
                clock[0] = 100.0
            write_manifest(path, value)

        with fake_runtime(self.corpus) as calls, patch.object(
            ev.time, "monotonic", side_effect=lambda: clock[0],
        ), patch.object(ev, "_manifest", side_effect=delayed_manifest):
            report = self.capture(total_timeout=1)
        self.assertEqual(calls, [])
        self.assertEqual(report["stop_reason"], "budget_exhausted")
        self.assertEqual(report["attempted"], 0)
        self.assertEqual(report["not_attempted"], 24)
        self.assertEqual(ev.replay(self.corpus, self.out), report)

    def test_deep_oracle_is_rejected_before_network(self):
        deep = None
        for _ in range(500):
            deep = [deep]
        self.corpus["cases"][0]["expected"] = {
            "status": "answer", "value": deep, "sources": [], "calls": [],
        }
        with patch.object(ev, "probe_models") as probe, patch.object(ev, "chat_completion") as call:
            with self.assertRaises(ValueError):
                self.capture()
            probe.assert_not_called()
            call.assert_not_called()

    def test_deep_reply_is_an_invalid_schema_not_a_grader_crash(self):
        candidate = copy.deepcopy(self.corpus["cases"][8]["expected"])
        deep = None
        for _ in range(500):
            deep = [deep]
        candidate["value"] = deep
        grade = ev.grade_case(self.corpus["cases"][8], response(
            self.corpus["cases"][8], content=json.dumps(candidate),
        ))
        self.assertTrue(grade["json_valid"])
        self.assertFalse(grade["schema_valid"])
        self.assertFalse(grade["pass"])

    def test_preflight_failure_and_absent_model_never_infer(self):
        for index, (status, ids, reason) in enumerate([
            ("timeout", [], "preflight_failed"), ("reachable", [], "model_absent"),
        ]):
            with self.subTest(reason=reason):
                self.out = Path(self.temp.name) / f"preflight-{index}"
                with patch.object(ev, "probe_models", return_value={
                    "status": status, "model_ids": ids, "origin": ORIGIN,
                }), patch.object(ev, "chat_completion") as call:
                    report = self.capture()
                call.assert_not_called()
                self.assertEqual(report["stop_reason"], reason)
                self.assertEqual(report["not_attempted"], 24)
                self.assertEqual(ev.replay(self.corpus, self.out), report)

    def test_duplicate_case_identity_is_refused(self):
        self.corpus["cases"][1]["id"] = self.corpus["cases"][0]["id"]
        path = Path(self.temp.name) / "duplicate.json"
        path.write_text(json.dumps(self.corpus))
        with self.assertRaises(ValueError):
            ev.load_corpus(path)

    def test_replay_refuses_modified_parameters(self):
        with fake_runtime(self.corpus):
            self.capture()
        path = self.out / "run.json"
        manifest = json.loads(path.read_text())
        manifest["parameters"]["max_tokens"] += 1
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            ev.replay(self.corpus, self.out)

    def test_replay_refuses_unknown_grader_revision(self):
        with fake_runtime(self.corpus):
            self.capture()
        path = self.out / "run.json"
        manifest = json.loads(path.read_text())
        manifest["grader"]["version"] += 1
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            ev.replay(self.corpus, self.out)

    def test_compare_is_quality_only_and_refuses_mismatched_budgets(self):
        left = self.out
        with fake_runtime(self.corpus):
            self.capture()
        self.out = Path(self.temp.name) / "right"
        with fake_runtime(self.corpus):
            self.capture(max_tokens=256)
        with self.assertRaises(ValueError):
            ev.compare(self.corpus, left, self.out)
        report = ev.compare(self.corpus, left, left)
        self.assertEqual(report["comparison_scope"], "authored_fixture_quality_only")
        self.assertEqual(report["latency_comparison"], "unqualified")
        self.assertIsNone(report["selected_model"])


if __name__ == "__main__":
    unittest.main()
