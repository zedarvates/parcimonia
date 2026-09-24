"""The exported coverage report must identify the corpus it measured."""

import json
import subprocess
import sys
from pathlib import Path


def test_export_records_the_input_revision(tmp_path):
    corpus = tmp_path / "revision.json"
    report = tmp_path / "report.json"
    corpus.write_text(
        json.dumps(
            {
                "revision_id": "fixed-revision-123",
                "prompts": [
                    {"id": "p1", "text": "extract the columns", "count": 2},
                ],
            }
        ),
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[1] / "examples" / "real_asks_lane.py"
    result = subprocess.run(
        [sys.executable, str(script), "--corpus", str(corpus), "--out", str(report)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["revision_id"] == "fixed-revision-123"
    assert payload["corpus"] == str(corpus)
    assert "extract the columns" not in report.read_text(encoding="utf-8")
