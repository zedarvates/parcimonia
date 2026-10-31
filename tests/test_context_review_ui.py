from tiberium_ai.context_review import build_context_review_pack
from tiberium_ai.context_review_ui import render_context_review
from pathlib import Path
import shutil
import subprocess
import pytest


def test_untrusted_source_text_is_json_data_and_cannot_terminate_a_script():
    text = '</script><img src=x onerror="alert(1)">'
    packet = build_context_review_pack([{"text": text, "sources": []}], corpus_revision="fixture")
    html = render_context_review(packet)
    assert text not in html
    assert '\\u003c/script\\u003e' in html
    assert 'innerHTML' not in html
    assert "connect-src 'none'" in html


def test_generated_ui_logic_on_synthetic_cases_without_a_browser(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("Node runtime unavailable for generated UI script verification")
    packet = build_context_review_pack([{"text": "extraire les colonnes du document", "sources": []},
        {"text": "vérifier les colonnes du rapport", "sources": []}], corpus_revision="fixture")
    packet["parent_pack_id"] = "fixture-parent"
    for i, case in enumerate(packet["cases"]):
        case["source_group"] = f"fixture-{i}"
    path = tmp_path / "review.html"
    path.write_text(render_context_review(packet), encoding="utf-8")
    result = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("context_review_ui_checks.cjs")), str(path)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
