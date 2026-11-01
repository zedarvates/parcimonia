"""Exercise the CLI's explicit writes and failure/recovery behavior offline."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tiberium_ai.knowledge_cli import main, _write_new


class TestKnowledgeCli(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def initial(self):
        path = self.root / "index0.json"
        code, out, err = self.run_cli("create", "fixture", "--out", str(path))
        self.assertEqual((code, err), (0, ""))
        return path, json.loads(out)["index_hash"]

    def batch(self):
        records = []
        for name, channel, text in (
            ("cloud", "cloud", "toiture escalier dimensions"),
            ("wiki", "wiki", "toiture escalier controle"),
        ):
            records.append({"id": name, "version": "v1", "feed_id": name,
                            "channel": channel, "project": "fixture", "uri": "fixture:" + name,
                            "locator": "message:1", "timestamp": "2026-11-01",
                            "state": "active", "text": text})
        value = {"schema": "parcimonia.knowledge-update/v1", "upserts": records,
                 "removals": [], "coverage": [{"id": name, "status": "partial"}
                                               for name in ("cloud", "wiki")]}
        path = self.root / "batch.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_create_update_candidates_roundtrip(self):
        initial, head = self.initial()
        batch, target = self.batch(), self.root / "index1.json"
        code, out, err = self.run_cli("update", str(initial), str(batch),
                                      "--out", str(target), "--expected-head", head)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["delta"]["added"], 2)
        code, out, err = self.run_cli("candidates", str(target), "--fragment-id", "cloud")
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertTrue(result["coverage_incomplete"])
        self.assertEqual(result["matches"][0]["target"]["id"], "wiki")
        self.assertEqual(json.loads(initial.read_text(encoding="utf-8"))["generation"], 0)

    def test_existing_output_is_never_overwritten(self):
        path, _ = self.initial()
        before = path.read_bytes()
        code, _, err = self.run_cli("create", "another", "--out", str(path))
        self.assertEqual(code, 2)
        self.assertTrue(err)
        self.assertEqual(path.read_bytes(), before)

    def test_stale_head_writes_nothing(self):
        initial, _ = self.initial()
        target = self.root / "new.json"
        code, _, _ = self.run_cli("update", str(initial), str(self.batch()),
                                  "--out", str(target), "--expected-head", "0" * 64)
        self.assertEqual(code, 2)
        self.assertFalse(target.exists())

    def test_duplicate_json_keys_refused(self):
        path = self.root / "duplicate.json"
        path.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
        code, _, _ = self.run_cli("candidates", str(path), "--fragment-id", "cloud")
        self.assertEqual(code, 2)

    def test_final_input_symlink_refused(self):
        source, _ = self.initial()
        link = self.root / "link.json"
        try:
            link.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable on this host")
        code, _, _ = self.run_cli("candidates", str(link), "--fragment-id", "cloud")
        self.assertEqual(code, 2)

    def test_existing_output_symlink_refused(self):
        source, _ = self.initial()
        link = self.root / "link.json"
        try:
            link.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable on this host")
        original = source.read_bytes()
        code, _, _ = self.run_cli("create", "new", "--out", str(link))
        self.assertEqual(code, 2)
        self.assertEqual(source.read_bytes(), original)

    def test_oversized_input_refused_before_json(self):
        path = self.root / "large.json"
        with path.open("wb") as stream:
            stream.truncate(2 * 1024 * 1024 + 1)
        code, _, _ = self.run_cli("candidates", str(path), "--fragment-id", "cloud")
        self.assertEqual(code, 2)

    def test_malformed_utf8_refused(self):
        path = self.root / "invalid.json"
        path.write_bytes(b"\xff")
        code, _, _ = self.run_cli("candidates", str(path), "--fragment-id", "cloud")
        self.assertEqual(code, 2)

    @unittest.skipIf(os.name == "nt", "Windows permissions use caller ACLs")
    def test_created_snapshot_has_private_mode(self):
        path, _ = self.initial()
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_write_can_be_retried(self):
        target = self.root / "recover.json"
        real_fdopen = os.fdopen

        class FailedStream:
            def __init__(self, descriptor, mode):
                self.stream = real_fdopen(descriptor, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, payload):
                self.stream.write(payload[:2])
                self.stream.flush()
                raise OSError("fixture: output device unavailable")

        with patch("tiberium_ai.knowledge_cli.os.fdopen", FailedStream):
            with self.assertRaises(OSError):
                _write_new(str(target), {"fixture": True})
        self.assertFalse(target.exists())
        _write_new(str(target), {"fixture": True})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"fixture": True})


if __name__ == "__main__":
    unittest.main()
