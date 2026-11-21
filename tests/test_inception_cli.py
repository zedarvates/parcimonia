"""Exercise real CLI processes and the durable operation/output boundary."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tiberium_ai.inception_cli import main


ROOT = Path(__file__).resolve().parents[1]


class TestInceptionCli(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = os.environ.copy()
        if self.environment.get("PARCIMONIA_RELEASE_INSTALL") == "1":
            self.environment.pop("PYTHONPATH", None)
        else:
            self.environment["PYTHONPATH"] = str(ROOT / "src")
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
        self.empty_heads = self.json_file("empty-heads.json", [])

    def json_file(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "tiberium_ai.inception_cli", *map(str, arguments)],
            cwd=self.root, env=self.environment, capture_output=True,
            text=True, encoding="utf-8", timeout=20,
        )

    def success(self, *arguments):
        process = self.run_cli(*arguments)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        return json.loads(process.stdout)

    def initial(self, name="cloud"):
        path = self.root / (name + ".sqlite")
        result = self.success("init", "--db", path, "--node", name)
        self.assertEqual(result["write"], "created")
        return path

    def lesson(self, db, *, event_id="event-lesson", scope="local", summary="Échec gardé : pas de preuve."):
        payload = self.json_file(event_id + "-payload.json", {
            "summary": summary, "limits": "Observation de fixture, pas une cause établie.",
        })
        event = self.success(
            "append", "--db", db, "--project", "fixture", "--kind", "lesson",
            "--record", event_id, "--input", payload, "--expected-heads", self.empty_heads,
            "--event-id", event_id, "--scope", scope,
        )
        return event, payload

    def checkpoint(self, db, *, event_id="event-checkpoint", scope="shared"):
        payload = self.json_file(event_id + "-payload.json", {
            "goal": "Poursuivre les essais de mémoire sans perdre les échecs.",
            "state": "Première discussion terminée ; résultat encore partiel.",
            "next_action": "Comparer les deux copies avec le même témoin.",
            "acceptance": "Retrouver les mêmes références après reprise.",
            "decision_ids": [], "outcome_ids": [],
            "open_actions": ["Relire la source entière avant de conclure."],
        })
        event = self.success(
            "checkpoint", "--db", db, "--project", "fixture", "--input", payload,
            "--expected-heads", self.empty_heads, "--event-id", event_id, "--scope", scope,
        )
        return event, payload

    def heads(self, db, kind, record):
        return self.success("heads", "--db", db, "--project", "fixture",
                            "--kind", kind, "--record", record)

    def test_checkpoint_resume_and_identical_retry_work_across_processes(self):
        db = self.initial()
        event, payload = self.checkpoint(db, scope="local")
        self.assertEqual(event["scope"], "local")
        self.assertEqual(self.heads(db, "checkpoint", "main"), [event["id"]])
        resumed = self.success("resume", "--db", db, "--project", "fixture")
        self.assertIn("Comparer les deux copies", json.dumps(resumed, ensure_ascii=False))
        # The identical event ID is an idempotent retry even with its old heads.
        repeated = self.success(
            "checkpoint", "--db", db, "--project", "fixture", "--input", payload,
            "--expected-heads", self.empty_heads, "--event-id", event["id"], "--scope", "local",
        )
        self.assertEqual(repeated, event)
        self.assertEqual(self.heads(db, "checkpoint", "main"), [event["id"]])
        self.assertEqual(self.success("resume", "--db", db),
                         self.success("projects", "--db", db))

    def test_stale_heads_do_not_append_or_write_output(self):
        db = self.initial()
        event, payload = self.checkpoint(db)
        target = self.root / "refused.json"
        failed = self.run_cli(
            "checkpoint", "--db", db, "--project", "fixture", "--input", payload,
            "--expected-heads", self.empty_heads, "--event-id", "another-event", "--out", target,
        )
        self.assertEqual(failed.returncode, 2)
        self.assertFalse(json.loads(failed.stderr)["operation_completed"])
        self.assertFalse(target.exists())
        self.assertEqual(self.heads(db, "checkpoint", "main"), [event["id"]])

    def test_export_receive_ack_and_replay_preserve_shared_context(self):
        cloud, local = self.initial("cloud"), self.initial("local")
        event, _ = self.checkpoint(cloud)
        self.lesson(cloud, event_id="local-only-note")
        bundle_path = self.root / "cloud-to-local.json"
        bundle = self.success("sync", "export", "--db", cloud, "--project", "fixture",
                              "--peer", "local", "--out", bundle_path)
        self.assertNotIn("local-only-note", json.dumps(bundle))
        retry_bundle = self.success("sync", "export", "--db", cloud, "--project", "fixture",
                                    "--peer", "local", "--out", self.root / "bundle-retry.json")
        self.assertEqual(retry_bundle, bundle)
        receipt_path = self.root / "local-receipt.json"
        receipt = self.success("sync", "receive", "--db", local,
                               "--input", bundle_path, "--out", receipt_path)
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(self.heads(local, "checkpoint", "main"), [event["id"]])
        self.assertEqual(self.heads(local, "lesson", "local-only-note"), [])
        repeated = self.success("sync", "receive", "--db", local, "--input", bundle_path,
                                "--out", self.root / "receipt-retry.json")
        self.assertEqual(repeated, receipt)
        ack = self.success("sync", "ack", "--db", cloud, "--input", receipt_path)
        self.assertEqual(ack["status"], "acknowledged")
        status = self.success("status", "--db", cloud, "--project", "fixture", "--peer", "local")
        self.assertEqual(status["pending_event_count"], 0)
        self.assertEqual(status["pending_batches"], [])
        self.assertEqual(self.heads(local, "checkpoint", "main"), [event["id"]])
        resumed = self.success("resume", "--db", local, "--project", "fixture")
        self.assertIn("Comparer les deux copies", json.dumps(resumed, ensure_ascii=False))

    def test_identity_collision_writes_receipt_with_exit_three_and_no_partial_ingestion(self):
        cloud, local = self.initial("cloud"), self.initial("local")
        local_event, _ = self.lesson(local, event_id="same-id", scope="shared", summary="Version locale.")
        self.lesson(cloud, event_id="same-id", scope="shared", summary="Version différente du cloud.")
        self.checkpoint(cloud)
        batch = self.root / "conflicting-batch.json"
        original_batch = self.success("sync", "export", "--db", cloud, "--project", "fixture",
                                      "--peer", "local", "--out", batch)
        receipt = self.root / "conflict-receipt.json"
        process = self.run_cli("sync", "receive", "--db", local, "--input", batch, "--out", receipt)
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(process.stderr, "")
        report = json.loads(process.stdout)
        self.assertEqual(report["status"], "conflict")
        self.assertEqual(report["conflicts"], ["same-id"])
        self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), report)
        self.assertEqual(self.heads(local, "lesson", "same-id"), [local_event["id"]])
        self.assertEqual(self.heads(local, "checkpoint", "main"), [])
        refused_ack = self.run_cli("sync", "ack", "--db", cloud, "--input", receipt)
        self.assertEqual(refused_ack.returncode, 2)
        replay = self.success("sync", "export", "--db", cloud, "--project", "fixture",
                              "--peer", "local", "--out", self.root / "conflicting-retry.json")
        self.assertEqual(replay, original_batch)

    def test_sources_and_outcome_reason_survive_a_fresh_process(self):
        db = self.initial()
        sources = self.json_file("sources.json", [{
            "id": "fixture-report", "version": "v1", "uri": "fixture:verification",
            "sha256": "a" * 64, "availability": "available",
        }])
        outcome = self.json_file("outcome.json", {
            "summary": "Le témoin a échoué ; la cause reste une hypothèse.",
            "result": "failure", "verification": "verified",
            "why": "Le contexte pouvait être périmé ; vérifier la révision exacte.",
            "cause_status": "hypothesis",
        })
        event = self.success(
            "append", "--db", db, "--project", "fixture", "--kind", "outcome",
            "--record", "attempt-1", "--input", outcome, "--sources", sources,
            "--expected-heads", self.empty_heads, "--event-id", "outcome-1",
        )
        checkpoint = self.json_file("with-outcome.json", {
            "goal": "Reprendre le témoin", "state": "Échec conservé",
            "next_action": "Contrôler la révision", "acceptance": "Même témoin, sources relues",
            "decision_ids": [], "outcome_ids": [event["id"]], "open_actions": [],
        })
        self.success("checkpoint", "--db", db, "--project", "fixture", "--input", checkpoint,
                     "--expected-heads", self.empty_heads, "--event-id", "checkpoint-with-outcome")
        resumed = self.success("resume", "--db", db, "--project", "fixture")
        self.assertEqual(resumed["outcomes"][0]["payload"]["result"], "failure")
        self.assertEqual(resumed["outcomes"][0]["payload"]["cause_status"], "hypothesis")
        self.assertEqual(resumed["outcomes"][0]["sources"][0]["uri"], "fixture:verification")
        self.assertTrue(resumed["revalidation_required"])

    def test_wrong_receiver_writes_no_receipt_or_events(self):
        cloud, stranger = self.initial("cloud"), self.initial("stranger")
        self.checkpoint(cloud)
        bundle = self.root / "for-local.json"
        self.success("sync", "export", "--db", cloud, "--project", "fixture",
                     "--peer", "local", "--out", bundle)
        receipt = self.root / "refused-receipt.json"
        failed = self.run_cli("sync", "receive", "--db", stranger, "--input", bundle, "--out", receipt)
        self.assertEqual(failed.returncode, 2)
        self.assertFalse(receipt.exists())
        self.assertEqual(self.heads(stranger, "checkpoint", "main"), [])

    def test_existing_output_is_refused_before_database_creation_or_append(self):
        target = self.root / "keep.json"
        target.write_bytes(b"original")
        db = self.root / "new.sqlite"
        failed = self.run_cli("init", "--db", db, "--node", "new", "--out", target)
        self.assertEqual(failed.returncode, 2)
        self.assertFalse(db.exists())
        db = self.initial()
        payload = self.json_file("checkpoint.json", {
            "goal": "fixture", "state": "fixture", "next_action": "fixture",
            "acceptance": "fixture", "decision_ids": [], "outcome_ids": [], "open_actions": [],
        })
        failed = self.run_cli(
            "checkpoint", "--db", db, "--project", "fixture", "--input", payload,
            "--expected-heads", self.empty_heads, "--event-id", "refused", "--out", target,
        )
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(self.heads(db, "checkpoint", "main"), [])
        self.assertEqual(target.read_bytes(), b"original")

    def test_output_cannot_replace_database_or_use_missing_directory(self):
        db = self.root / "new.sqlite"
        failed = self.run_cli("init", "--db", db, "--node", "new", "--out", db)
        self.assertEqual(failed.returncode, 2)
        self.assertFalse(db.exists())
        failed = self.run_cli("init", "--db", db, "--node", "new",
                              "--out", self.root / "missing" / "report.json")
        self.assertEqual(failed.returncode, 2)
        self.assertFalse(db.exists())

    def test_read_only_command_does_not_create_missing_database(self):
        missing = self.root / "missing.sqlite"
        process = self.run_cli("resume", "--db", missing, "--project", "fixture")
        self.assertEqual(process.returncode, 2)
        self.assertFalse(missing.exists())

    def test_invalid_json_and_oversized_input_do_not_append(self):
        db = self.initial()
        malformed = self.root / "ambiguous.json"
        malformed.write_text('{"summary":"one","summary":"two","limits":"fixture"}', encoding="utf-8")
        oversized = self.root / "large.json"
        with oversized.open("wb") as stream:
            stream.truncate(2 * 1024 * 1024 + 1)
        for source in (malformed, oversized):
            with self.subTest(source=source.name):
                process = self.run_cli(
                    "append", "--db", db, "--project", "fixture", "--kind", "lesson",
                    "--record", "bad", "--input", source, "--expected-heads", self.empty_heads,
                    "--event-id", "bad-event",
                )
                self.assertEqual(process.returncode, 2)
                self.assertFalse(json.loads(process.stderr)["operation_completed"])
                self.assertEqual(self.heads(db, "lesson", "bad"), [])

    def test_final_input_and_dangling_output_links_are_refused(self):
        db = self.initial()
        payload = self.json_file("lesson.json", {"summary": "fixture", "limits": "fixture"})
        link, target, dangling = self.root / "input-link.json", self.root / "missing.json", self.root / "output-link.json"
        loop = self.root / "self-link.json"
        try:
            link.symlink_to(payload)
            dangling.symlink_to(target)
            loop.symlink_to(loop.name)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable on this host")
        args = ["append", "--db", db, "--project", "fixture", "--kind", "lesson",
                "--record", "bad", "--expected-heads", self.empty_heads, "--event-id", "bad-event"]
        self.assertEqual(self.run_cli(*args, "--input", link).returncode, 2)
        self.assertEqual(self.run_cli(*args, "--input", payload, "--out", dangling).returncode, 2)
        self.assertEqual(self.run_cli(*args, "--input", payload, "--out", loop).returncode, 2)
        self.assertTrue(dangling.is_symlink())
        self.assertTrue(loop.is_symlink())
        self.assertFalse(target.exists())
        self.assertEqual(self.heads(db, "lesson", "bad"), [])

    def test_output_failure_reports_completed_event_and_retry_recovers_it(self):
        db = self.initial()
        payload = self.json_file("lesson.json", {"summary": "fixture", "limits": "fixture"})
        target = self.root / "report.json"
        args = ["append", "--db", str(db), "--project", "fixture", "--kind", "lesson",
                "--record", "durable", "--input", str(payload), "--expected-heads", str(self.empty_heads),
                "--event-id", "durable-event", "--out", str(target)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("tiberium_ai.inception_cli._write_new", side_effect=OSError("fixture write failure")):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(args)
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(json.loads(stderr.getvalue())["operation_completed"])
        self.assertFalse(target.exists())
        self.assertEqual(self.heads(db, "lesson", "durable"), ["durable-event"])
        recovered = self.success(*args)
        self.assertEqual(recovered["id"], "durable-event")
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), recovered)
        self.assertEqual(self.heads(db, "lesson", "durable"), ["durable-event"])

    @unittest.skipIf(os.environ.get("PARCIMONIA_RELEASE_INSTALL") == "1", "Source-checkout launcher")
    def test_script_entrypoint_works_outside_checkout(self):
        process = subprocess.run(
            [sys.executable, "-I", "-B", str(ROOT / "scripts" / "parcimonia_inception.py"),
             "init", "--db", str(self.root / "script.sqlite"), "--node", "script-node"],
            cwd=self.root, env=self.environment, capture_output=True,
            text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["node_id"], "script-node")


if __name__ == "__main__":
    unittest.main()
