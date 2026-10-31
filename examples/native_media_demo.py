"""Observe authored local media fixtures with explicitly installed tools.

WAV silence uses only the standard library. MP4 examples additionally invoke
installed ffmpeg to encode authored silence or a solid RGB frame. No source
media, model, encoder or executable is downloaded. These fixtures exercise
container/stream metadata, not recognition of a scene, speech or sound event.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
import wave

from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.native_process import run_bounded


KINDS = ("wav", "audio-mp4", "video-mp4")
MAX_FIXTURE_BYTES = 1024 * 1024
GENERATION_TIMEOUT_SECONDS = 5.0


def wav_fixture() -> bytes:
    """Return 0.2 seconds of authored mono PCM silence, without ffmpeg."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


def _record(result: dict) -> dict:
    return {
        "phase": "generate", "status": result["status"],
        "returncode": result["returncode"], "started": result["started"],
        "stdout_complete": result["stdout_complete"],
        "stderr_complete": result["stderr_complete"], "error": result["error"],
        "stdout_sha256": hashlib.sha256(result["stdout"]).hexdigest(),
        "stderr_sha256": hashlib.sha256(result["stderr"]).hexdigest(),
        "elapsed_ms": result["elapsed_ms"],
    }


def _read_fixture(path: Path) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= MAX_FIXTURE_BYTES:
        raise ValueError("Generated fixture must be a regular file of at most one MiB.")
    with path.open("rb") as stream:
        payload = stream.read(MAX_FIXTURE_BYTES)
    after = path.lstat()
    signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if len(payload) != before.st_size or signature(before) != signature(after):
        raise ValueError("Generated fixture changed during its bounded read.")
    return payload


def generate_mp4_fixture(kind: str) -> tuple[bytes | None, dict]:
    """Encode one authored fixture privately and return bounded call metadata.

    This ffmpeg invocation belongs to the demonstration, not the inspection or
    native media probe. Failed generation is reported without inventing media.
    """
    if type(kind) is not str or kind not in {"audio-mp4", "video-mp4"}:
        raise ValueError("MP4 fixture kind must be audio-mp4 or video-mp4.")
    generation = {
        "status": "unavailable", "backend": "ffmpeg", "executable": None,
        "kind": kind, "reason_codes": [], "native_calls": [], "diagnostic": None,
        "max_fixture_bytes": MAX_FIXTURE_BYTES,
        "timeout_s": GENERATION_TIMEOUT_SECONDS,
    }
    selected = shutil.which("ffmpeg")
    if selected is None:
        generation["reason_codes"] = ["ffmpeg_not_found"]
        return None, generation
    try:
        executable = str(Path(selected).resolve(strict=True))
        generation["executable"] = executable
        with tempfile.TemporaryDirectory(prefix="parcimonia-media-fixture-") as temporary:
            directory = Path(temporary)
            output = directory / "fixture.mp4"
            common = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
            if kind == "audio-mp4":
                seed = directory / "authored.wav"
                seed.write_bytes(wav_fixture())
                argv = common + [
                    "-i", str(seed), "-map", "0:a:0", "-vn", "-c:a", "aac",
                    "-threads", "1", "-t", "0.2", "-fs", str(MAX_FIXTURE_BYTES),
                    "-f", "mp4", str(output),
                ]
            else:
                seed = directory / "authored.rgb"
                seed.write_bytes(b"\x18\x60\xa0" * (16 * 16))
                argv = common + [
                    "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "16x16",
                    "-framerate", "5", "-i", str(seed), "-map", "0:v:0", "-an",
                    "-c:v", "mpeg4", "-threads", "1", "-pix_fmt", "yuv420p",
                    "-frames:v", "1", "-fs", str(MAX_FIXTURE_BYTES), "-f", "mp4", str(output),
                ]
            result = run_bounded(
                argv, deadline=time.monotonic() + GENERATION_TIMEOUT_SECONDS,
                max_stdout_bytes=4096, max_stderr_bytes=16384,
                cwd=temporary, env=dict(os.environ, LC_ALL="C"),
            )
            generation["native_calls"].append(_record(result))
            generation["diagnostic"] = result["stderr"].decode("utf-8", errors="replace")[:4096] or None
            if result["status"] != "completed":
                generation["status"] = "unavailable" if result["status"] == "failed_to_start" else "indeterminate"
                generation["reason_codes"] = ["ffmpeg_generation_" + result["status"]]
                return None, generation
            if result["returncode"] != 0:
                generation["status"] = "failed"
                generation["reason_codes"] = ["ffmpeg_generation_exit_nonzero"]
                return None, generation
            if result["error"] is not None or result["stdout_complete"] is not True or result["stderr_complete"] is not True:
                generation["status"] = "failed"
                generation["reason_codes"] = ["ffmpeg_generation_response_incomplete"]
                return None, generation
            payload = _read_fixture(output)
            generation["status"] = "completed"
            generation["fixture_bytes"] = len(payload)
            generation["fixture_sha256"] = hashlib.sha256(payload).hexdigest()
            return payload, generation
    except (OSError, ValueError, RuntimeError) as exc:
        generation["status"] = "failed"
        generation["reason_codes"] = ["ffmpeg_generation_fixture_unusable"]
        generation["diagnostic"] = f"{type(exc).__name__}: {exc}"
        return None, generation


def run_demo(kind: str) -> dict:
    """Probe an authored complete fixture and retain proposed stream tags."""
    if type(kind) is not str or kind not in KINDS:
        raise ValueError("kind must be wav, audio-mp4 or video-mp4.")
    generation = None
    if kind == "wav":
        data = wav_fixture()
    else:
        data, generation = generate_mp4_fixture(kind)
    result = {
        "data_origin": "authored_fixture", "generation": generation,
        "observation": None, "enriched": None, "search": None,
    }
    if data is None:
        return result
    from tiberium_ai.asset_media_enrichment import enrich_asset_with_media
    from tiberium_ai.asset_media_probe import probe_asset_media

    identity = {
        "filename": "fixture.wav" if kind == "wav" else "fixture.mp4",
        "source_id": f"fixture:media:{kind}", "revision": "authored-v1",
    }
    inspection = inspect_asset(data, **identity)
    observation = probe_asset_media(data, **identity)
    result["observation"] = observation
    if observation["status"] == "completed":
        enriched = enrich_asset_with_media(inspection, observation)
        result["enriched"] = enriched
        modality = "video" if kind == "video-mp4" else "audio"
        result["search"] = search_asset_reports([enriched], tags=[f"modality:{modality}"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=KINDS)
    result = run_demo(parser.parse_args().kind)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return 0 if result["observation"] is not None and result["observation"]["status"] == "completed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
