"""Untrusted CLI input must fail before indexing, caching or emitting a verdict."""
import json

import pytest

from tiberium_ai.agent_recipes.__main__ import main


@pytest.mark.parametrize("text", [
    '{"change":{"path":"x.py","after":"safe","after":"eval(user)"},"rules":[]}',
    '{"change":{"path":"x.py","after":"safe"},"rules":[],"extra":NaN}',
    '{"change":{"path":"x.py","after":"safe"},"rules":[],"extra":Infinity}',
    '{"change":{"path":"x.py","after":"safe"},"rules":[],"extra":1e999}',
])
def test_cli_rejects_ambiguous_or_nonfinite_json(tmp_path, capsys, text):
    source = tmp_path / "request.json"
    source.write_text(text, encoding="utf-8")
    assert main(["rules", "--input", str(source), "--enforce-rules"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error"] == "ValueError"
    assert "result" not in result


def test_ambiguous_input_cannot_create_a_database(tmp_path, capsys):
    source = tmp_path / "request.json"
    source.write_text('{"root":"first","root":"second"}', encoding="utf-8")
    database = tmp_path / "skills.sqlite"
    assert main(["index", "--input", str(source), "--db", str(database)]) == 2
    assert not database.exists()
    assert "error" in json.loads(capsys.readouterr().out)


def test_ambiguous_recorded_answers_are_rejected(tmp_path, capsys):
    source = tmp_path / "request.json"
    source.write_text('{"records":[]}', encoding="utf-8")
    answers = tmp_path / "answers.json"
    answers.write_text('{"q":{},"q":{}}', encoding="utf-8")
    assert main(["feedback", "--input", str(source), "--answers", str(answers)]) == 2
    assert "error" in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("stdin", [False, True])
def test_cli_rejects_oversized_input_before_creating_database(tmp_path, capsys, monkeypatch, stdin):
    import io
    from tiberium_ai.agent_recipes import __main__ as cli

    monkeypatch.setattr(cli, "MAX_INPUT_BYTES", 32)
    text = json.dumps({"root": "x" * 40})
    database = tmp_path / "skills.sqlite"
    argv = ["index", "--db", str(database)]
    if stdin:
        monkeypatch.setattr("sys.stdin", io.StringIO(text))
    else:
        source = tmp_path / "request.json"
        source.write_text(text, encoding="utf-8")
        argv += ["--input", str(source)]
    assert main(argv) == 2
    assert not database.exists()
    assert "error" in json.loads(capsys.readouterr().out)


def test_cli_preserves_valid_french_input(tmp_path, capsys):
    source = tmp_path / "request.json"
    source.write_text(json.dumps({"change": {"path": "été.py", "after": "value = 1"},
                                  "rules": []}, ensure_ascii=False), encoding="utf-8")
    assert main(["rules", "--input", str(source), "--enforce-rules"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["data"]["verdict"] == "pass"


def test_module_command_and_public_api_report_the_same_version(capsys):
    from tiberium_ai import __version__

    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == f"Parcimonia {__version__}"
