"""Authored image fixtures exercise preparation, without model or decoder calls."""

import base64
import binascii
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from unittest.mock import patch
import zlib

import pytest

from tiberium_ai.local_chat import MAX_IMAGE_BYTES, _request


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "local_vision_request", ROOT / "examples" / "local_vision_request.py",
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def png(width=1, height=1):
    def chunk(name, value):
        data = name + value
        return struct.pack(">I", len(value)) + data + struct.pack(">I", binascii.crc32(data))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x20\x40\x60"))
            + chunk(b"IEND", b""))


def jpeg():
    # Frame headers alone exercise container inspection; pixels are not decoded.
    frame = bytes([8]) + struct.pack(">HH", 1, 1) + bytes([3, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0])
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(frame) + 2) + frame + b"\xff\xd9"


def invoke(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(builder.sys, "stdout", stdout), patch.object(builder.sys, "stderr", stderr):
        code = builder.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def args(path, **options):
    values = {"task-id": "vision-fixture", "model": "local-fixture", "prompt": "Observe le rendu."}
    values.update(options)
    result = [part for key, value in values.items() for part in ("--" + key, str(value))]
    return result + ["--image", str(path)]


def test_png_and_jpeg_signature_overrides_filename_and_preserves_bytes(tmp_path):
    first, second = tmp_path / "reference.not-png", tmp_path / "render.png"
    first.write_bytes(png())
    second.write_bytes(jpeg())
    before = {path: path.read_bytes() for path in (first, second)}
    with patch("socket.socket", side_effect=AssertionError("network forbidden")):
        request = builder.build_request(
            task_id="vision-fixture", model="local-fixture", prompt="Compare ces références.",
            image_paths=[str(first), str(second)], max_tokens=64, temperature=0.2,
        )
    assert request["schema_version"] == 2
    parts = request["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Compare ces références."}
    for part, path, mime in zip(parts[1:], (first, second), ("image/png", "image/jpeg")):
        prefix, encoded = part["image_url"]["url"].split(",", 1)
        assert prefix == f"data:{mime};base64"
        assert base64.b64decode(encoded, validate=True) == before[path]
        assert path.read_bytes() == before[path]
    _request(request["model"], request["messages"], 64, 0.2, request_schema_version=2)
    assert set(tmp_path.iterdir()) == {first, second}
    assert str(tmp_path) not in json.dumps(request)


def test_cli_outputs_one_ascii_json_line_and_round_trips_french(tmp_path):
    path = tmp_path / "privé.png"
    path.write_bytes(png())
    code, stdout, stderr = invoke(args(path, prompt="Élargis l’épaule du modèle, sans modifier sa tête."))
    assert code == 0 and stderr == ""
    assert stdout.isascii() and len(stdout.splitlines()) == 1
    value = json.loads(stdout)
    assert value["messages"][0]["content"][0]["text"] == "Élargis l’épaule du modèle, sans modifier sa tête."
    assert "privé" not in stdout and str(tmp_path) not in stdout
    assert value["max_tokens"] == 1024 and value["temperature"] == 0.0


@pytest.mark.parametrize("kind", ["absent", "directory", "invalid", "oversize", "zero-width", "broken-png"])
def test_invalid_files_fail_without_partial_output_or_private_path(tmp_path, kind):
    path = tmp_path / "private-reference-file.png"
    if kind == "directory":
        path.mkdir()
    elif kind == "invalid":
        path.write_bytes(b"private image content")
    elif kind == "oversize":
        path.write_bytes(png() + b"x" * MAX_IMAGE_BYTES)
    elif kind == "zero-width":
        path.write_bytes(png(0, 1))
    elif kind == "broken-png":
        path.write_bytes(b"\x89PNG\r\n\x1a\nprivate image content")
    code, stdout, stderr = invoke(args(path))
    assert code == 2 and stdout == ""
    assert stderr == "local vision request preparation failed\n"


@pytest.mark.parametrize("target_kind", ["leaf", "parent"])
def test_symbolic_links_are_refused(tmp_path, target_kind):
    real = tmp_path / "real"
    real.mkdir()
    image = real / "reference.png"
    image.write_bytes(png())
    link = tmp_path / "private-link"
    try:
        link.symlink_to(image if target_kind == "leaf" else real, target_is_directory=target_kind == "parent")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic link creation unavailable")
    path = link if target_kind == "leaf" else link / image.name
    code, stdout, stderr = invoke(args(path))
    assert code == 2 and stdout == ""
    assert stderr == "local vision request preparation failed\n"
    assert image.read_bytes() == png()


@pytest.mark.parametrize("updates", [
    {"task-id": " private-task"}, {"task-id": "a" * 257}, {"model": ""},
    {"prompt": " "}, {"max-tokens": "secret-integer"}, {"max-tokens": 0},
    {"temperature": "secret-float"}, {"temperature": "nan"}, {"temperature": 3},
])
def test_invalid_options_are_sanitized(tmp_path, updates):
    path = tmp_path / "private-reference.png"
    path.write_bytes(png())
    code, stdout, stderr = invoke(args(path, **updates))
    assert code == 2 and stdout == ""
    assert stderr == "local vision request preparation failed\n"


def test_count_limits_and_unknown_options_refuse_before_output(tmp_path):
    path = tmp_path / "private-reference.png"
    path.write_bytes(png())
    for argv in (args(path) + ["--image", str(path)] * 2,
                 args(path) + ["--private-option", "private-value"],
                 ["--task-id", "private-task"]):
        code, stdout, stderr = invoke(argv)
        assert code == 2 and stdout == ""
        assert stderr == "local vision request preparation failed\n"
    with pytest.raises(ValueError):
        builder.build_request(task_id="task", model="model", prompt="text", image_paths=[])


def test_second_invalid_image_emits_no_partial_first_image(tmp_path):
    path = tmp_path / "reference.png"
    path.write_bytes(png())
    code, stdout, stderr = invoke(args(path) + ["--image", str(tmp_path / "private-missing.png")])
    assert code == 2 and stdout == ""
    assert stderr == "local vision request preparation failed\n"


def test_fifo_is_refused_without_blocking(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation unavailable")
    path = tmp_path / "private-fifo.png"
    os.mkfifo(path)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    completed = subprocess.run(
        [sys.executable, str(ROOT / "examples/local_vision_request.py"), *args(path)],
        capture_output=True, env=env, timeout=5, check=False,
    )
    assert completed.returncode == 2 and completed.stdout == b""
    assert completed.stderr == b"local vision request preparation failed\n"


def test_file_replaced_between_inspection_and_open_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "private-reference.png"
    path.write_bytes(png())
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(png(2, 1))
    native_open = builder.os.open

    def replace_before_open(filename, flags):
        replacement.replace(path)
        return native_open(filename, flags)

    monkeypatch.setattr(builder.os, "open", replace_before_open)
    code, stdout, stderr = invoke(args(path))
    assert code == 2 and stdout == ""
    assert stderr == "local vision request preparation failed\n"


def test_exact_image_byte_budget_is_accepted_and_one_more_is_refused(tmp_path):
    path = tmp_path / "reference.png"
    raw = png()
    path.write_bytes(raw + b"x" * (MAX_IMAGE_BYTES - len(raw)))
    code, stdout, stderr = invoke(args(path))
    assert code == 0 and stderr == "" and json.loads(stdout)["schema_version"] == 2
    with path.open("ab") as stream:
        stream.write(b"x")
    code, stdout, stderr = invoke(args(path))
    assert code == 2 and stdout == "" and stderr == "local vision request preparation failed\n"
