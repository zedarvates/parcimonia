"""Explicit file exports preserve pins and refuse nonselected/link sources."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tiberium_ai.knowledge_local_export import export_local_documents


class TestKnowledgeLocalExport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = "toiture escalier — dimensions\r\né🐈\r\n".encode("utf-8")
        (self.root / "selected.md").write_bytes(self.raw)
        self.item = {"id": "selected", "file": "selected.md",
                     "sha256": hashlib.sha256(self.raw).hexdigest(),
                     "version": "declared-v1", "project": "fixture",
                     "uri": "fixture:selected", "timestamp": "not_provided", "state": "active"}
        self.catalog = {"schema": "parcimonia.local-knowledge-catalog/v1", "documents": [self.item]}

    def run_export(self, catalog=None):
        return export_local_documents(self.catalog if catalog is None else catalog, root=self.root)

    def test_exact_utf8_crlf_and_declared_metadata_are_preserved(self):
        result = self.run_export()
        actual = result["documents"]["documents"][0]
        self.assertEqual(actual["text"].encode("utf-8"), self.raw)
        self.assertEqual(actual["version"], "declared-v1")
        self.assertEqual(actual["timestamp"], "not_provided")
        self.assertEqual(actual["uri"], "fixture:selected")
        self.assertEqual(result["manifest"]["files"][0]["sha256"], self.item["sha256"])

    def test_unlisted_files_are_not_exported(self):
        (self.root / "unlisted.txt").write_text("fixture not selected", encoding="utf-8")
        result = self.run_export()
        self.assertEqual(len(result["documents"]["documents"]), 1)
        self.assertEqual(result["manifest"]["file_count"], 1)

    def test_hash_mismatch_refuses_export(self):
        self.item["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.run_export()

    def test_unknown_fields_refuse_export(self):
        self.item["execute"] = "fixture: ignored instruction"
        with self.assertRaises(ValueError):
            self.run_export()

    def test_duplicate_identity_refused(self):
        (self.root / "other.md").write_bytes(self.raw)
        self.catalog["documents"].append({**self.item, "file": "other.md"})
        with self.assertRaises(ValueError):
            self.run_export()

    def test_duplicate_path_refused(self):
        self.catalog["documents"].append({**self.item, "id": "another"})
        with self.assertRaises(ValueError):
            self.run_export()

    def test_unsafe_paths_refused_before_read(self):
        for path in ("../selected.md", "/selected.md", "./selected.md", "dir//selected.md",
                     "dir/../selected.md", "dir\\selected.md", "C:/selected.md"):
            with self.subTest(path=path):
                item = {**self.item, "file": path}
                with self.assertRaises(ValueError):
                    self.run_export({**self.catalog, "documents": [item]})

    def test_final_symlink_refused(self):
        link = self.root / "link.md"
        try:
            link.symlink_to(self.root / "selected.md")
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        self.item["file"] = "link.md"
        with self.assertRaises((ValueError, OSError)):
            self.run_export()

    def test_parent_symlink_refused(self):
        folder = self.root / "actual"
        folder.mkdir()
        (folder / "selected.md").write_bytes(self.raw)
        try:
            (self.root / "linked").symlink_to(folder, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        self.item["file"] = "linked/selected.md"
        with self.assertRaises((ValueError, OSError)):
            self.run_export()

    def test_root_reparse_point_observation_is_refused(self):
        observation = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch("tiberium_ai.knowledge_local_export.Path.lstat", return_value=observation):
            with self.assertRaisesRegex(ValueError, "root"):
                self.run_export()

    def make_junction(self):
        target = self.root / "actual"
        target.mkdir()
        (target / "selected.md").write_bytes(self.raw)
        junction = self.root / "junction"
        run = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                             capture_output=True, text=True)
        if run.returncode:
            self.skipTest("NTFS junctions unavailable on this host")
        self.addCleanup(lambda: os.rmdir(junction) if junction.exists() else None)
        return junction

    @unittest.skipUnless(os.name == "nt", "Native NTFS junction check requires Windows")
    def test_native_windows_parent_junction_refused(self):
        self.make_junction()
        self.item["file"] = "junction/selected.md"
        with self.assertRaises(ValueError):
            self.run_export()

    @unittest.skipUnless(os.name == "nt", "Native NTFS junction check requires Windows")
    def test_native_windows_root_junction_refused(self):
        junction = self.make_junction()
        with self.assertRaises(ValueError):
            export_local_documents(self.catalog, root=junction)

    def test_invalid_utf8_refused_after_correct_raw_pin(self):
        (self.root / "selected.md").write_bytes(b"\xff")
        self.item["sha256"] = hashlib.sha256(b"\xff").hexdigest()
        with self.assertRaises((ValueError, UnicodeError)):
            self.run_export()

    def test_oversized_selected_file_refused(self):
        raw = b"x" * 65537
        (self.root / "selected.md").write_bytes(raw)
        self.item["sha256"] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError):
            self.run_export()

    def test_too_many_entries_refused_before_source_reads(self):
        self.catalog["documents"] = [{**self.item, "id": str(i), "file": str(i) + ".md"}
                                      for i in range(65)]
        with self.assertRaises(ValueError):
            self.run_export()

    def test_jsonl_is_read_as_text_not_executed(self):
        raw = b'{"text":"toiture escalier"}\n{"instruction":"fixture only"}\n'
        (self.root / "export.jsonl").write_bytes(raw)
        self.item.update(file="export.jsonl", sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.run_export()["documents"]["documents"][0]["text"], raw.decode("utf-8"))

    def test_manifest_contains_no_absolute_root_or_source_text(self):
        import json
        manifest = json.dumps(self.run_export()["manifest"])
        self.assertNotIn(str(self.root), manifest)
        self.assertNotIn("toiture", manifest)

    def test_input_catalog_is_not_mutated(self):
        before = deepcopy(self.catalog)
        self.run_export()
        self.assertEqual(self.catalog, before)


if __name__ == "__main__":
    unittest.main()
