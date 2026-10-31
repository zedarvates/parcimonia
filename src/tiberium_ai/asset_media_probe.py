"""Opt-in local observations of reported streams in forced containers.

The profile admits WAV, FLAC, Ogg and selected MPEG/QuickTime BMFF brands;
known image brands in the major or compatible list are refused before I/O.
The native probe receives only a private byte snapshot. Its reported streams
and durations do not establish a full decode, perceptual quality or semantic
content. Executable identity is observed, not authenticated; file-only protocol
options do not provide an OS sandbox. No player, transcription, subtitle-text
recognizer, model, download or fallback is started.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any

from .asset_text_extract import _IdentityError, _identity, _record, _text, _usable
from .media_evidence import parse_ffprobe_json
from .media_probe import probe_media
from .native_process import run_bounded
from .verification import hash_input

__all__ = ["PROFILE_ID", "BMFF_MEDIA_BRANDS", "SUPPORTED_DEMUXERS", "probe_asset_media"]

PROFILE_ID = "parcimonia.ffprobe-stream-profile/v1"
MAX_INPUT_BYTES = 1024 * 1024
MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 32 * 1024
SUPPORTED_DEMUXERS = {"wav": "wav", "flac": "flac", "ogg": "ogg", "iso_bmff": "mov"}
BMFF_MEDIA_BRANDS = frozenset({"isom", "iso2", "mp41", "mp42", "M4A ", "M4V ", "qt  "})
_BMFF_IMAGE_BRANDS = frozenset({
    "avif", "avis", "heic", "heix", "hevc", "hevx", "heim", "heis",
    "hevm", "hevs", "mif1", "msf1",
})
_ENTRIES = (
    "stream=index,codec_name,codec_type,width,height,sample_rate,channels,duration:"
    "stream_disposition=attached_pic:format=format_name,duration"
)
_VERSION = re.compile(
    r"ffprobe version ([0-9]{1,3})(?:\.[0-9A-Za-z.+_~-]+)(?: [\x20-\x7e]*)?\Z",
    re.ASCII,
)


def _version(result: dict[str, Any]) -> str:
    payload = result["stdout"] if result["stdout"] else result["stderr"]
    lines = payload.decode("utf-8").splitlines()
    line = lines[0] if lines else ""
    match = _VERSION.fullmatch(line) if len(line) <= 512 else None
    if match is None or int(match.group(1)) < 4:
        raise ValueError("backend_version_unusable")
    return line


def _supported_bmff_brands(data: bytes, header: dict[str, Any]) -> bool:
    """Admit this MPEG/QuickTime profile, excluding declared image brands."""
    values = {item["name"]: item["value"] for item in header["metadata"]}
    if values.get("major_brand") not in BMFF_MEDIA_BRANDS:
        return False
    end = values.get("declared_ftyp_bytes")
    brand_start = 16 if data[:4] == b"\x00\x00\x00\x01" else 8
    # Header validation has already bounded the complete, aligned ftyp box.
    if type(end) is not int or end > len(data) or end < brand_start + 8:
        return False
    compatible = data[brand_start + 8:end]
    if len(compatible) % 4:
        return False
    try:
        brands = [compatible[index:index + 4].decode("ascii") for index in range(0, len(compatible), 4)]
    except UnicodeError:
        return False
    return all(
        brand not in _BMFF_IMAGE_BRANDS and all(32 <= ord(character) <= 126 for character in brand)
        for brand in brands
    )


def probe_asset_media(
    data: bytes, *, filename: str, source_id: str, revision: str,
    executable: str | None = None, timeout_s: float = 10.0,
    complete: bool = True,
) -> dict[str, Any]:
    """Observe a complete supported sample with one bounded native profile.

    Invalid caller arguments raise ValueError. Unsupported input, missing
    tools, incomplete captures and native/parser failures yield distinct
    non-success observations. A common monotonic deadline includes header
    recognition, identities, snapshot, both native calls, parsing and cleanup;
    noninterruptible OS operations prevent a universal wall-time guarantee.
    """
    started_at = time.monotonic()
    if type(data) is not bytes or len(data) > MAX_INPUT_BYTES:
        raise ValueError("data must be bytes of at most one MiB.")
    for label, value in (("filename", filename), ("source_id", source_id), ("revision", revision)):
        _text(value, label)
    if executable is not None:
        _text(executable, "executable")
    if type(timeout_s) not in (int, float) or not 0 < timeout_s <= 30 or not math.isfinite(timeout_s):
        raise ValueError("timeout_s must be a finite number greater than zero and at most 30.")
    if type(complete) is not bool:
        raise ValueError("complete must be a boolean.")
    timeout_s = float(timeout_s)
    deadline = started_at + timeout_s
    digest = hashlib.sha256(data).hexdigest()
    source = {"id": source_id, "revision": revision, "filename": filename}
    profile: dict[str, Any] = {"id": PROFILE_ID, "source_format": None, "demuxer": None}
    report: dict[str, Any] = {
        "schema": "parcimonia.asset-media-observation/v1",
        "source": source, "input_hash": None,
        "sample_sha256": digest, "source_complete": complete,
        "backend": {"id": "ffprobe", "version": None, "executable": None, "executable_sha256": None},
        "profile": profile,
        "status": "indeterminate", "raw_json": None, "projection": None,
        "reason_codes": [], "native_calls": [], "elapsed_ms": 0.0,
        "limits": {
            "max_input_bytes": MAX_INPUT_BYTES, "max_stdout_bytes": MAX_OUTPUT_BYTES,
            "max_stderr_bytes": MAX_STDERR_BYTES, "max_executable_bytes": MAX_EXECUTABLE_BYTES,
            "native_media": "reported_streams_not_full_decode",
            "duration": "reported_or_estimated",
            "protocols": "file_only_not_os_sandbox", "os_sandbox": "not_provided",
            "fallback": "none", "native_inference": "none", "model_calls": 0,
            "executable_identity": "observed_before_and_after_not_atomic_or_authenticated",
            "deadline": "shared_monotonic_not_universal_wall_time_guarantee",
        },
    }

    def finish() -> dict[str, Any]:
        report["input_hash"] = hash_input({
            "source": source, "sample_sha256": digest, "complete": complete,
            "backend": "ffprobe", "executable_requested": executable,
            "timeout_s": timeout_s, "profile": profile,
        })
        now = time.monotonic()
        if report["status"] == "completed" and now >= deadline:
            report["status"] = "indeterminate"
            report["reason_codes"].append("deadline_exceeded")
        if report["status"] != "completed":
            report["raw_json"], report["projection"] = None, None
        report["elapsed_ms"] = max(0.0, (now - started_at) * 1000)
        report["reason_codes"] = sorted(set(report["reason_codes"]))
        return report

    if not complete:
        report["reason_codes"] = ["complete_source_required"]
        return finish()
    header = probe_media(data, complete=True)
    if header is None or header["format"] not in SUPPORTED_DEMUXERS:
        report["reason_codes"] = ["unsupported_media_format"]
        return finish()
    profile.update(source_format=header["format"], demuxer=SUPPORTED_DEMUXERS[header["format"]])
    if header["issues"]:
        report["reason_codes"] = ["media_header_unusable"]
        return finish()
    if header["format"] == "iso_bmff" and not _supported_bmff_brands(data, header):
        report["reason_codes"] = ["unsupported_bmff_brand"]
        return finish()

    selected = executable if executable is not None else shutil.which("ffprobe")
    if selected is None:
        report["status"] = "unavailable"
        report["reason_codes"] = ["executable_not_found"]
        return finish()
    try:
        tool = Path(selected).resolve(strict=True)
        if not tool.is_file():
            raise OSError("not_a_regular_executable")
        report["backend"]["executable"] = str(tool)
        before_hash = _identity(tool, deadline)
        report["backend"]["executable_sha256"] = before_hash
    except TimeoutError:
        report["reason_codes"] = ["deadline_exceeded"]
        return finish()
    except _IdentityError as exc:
        report["reason_codes"] = [str(exc)]
        return finish()
    except (OSError, RuntimeError):
        report["status"] = "unavailable"
        report["reason_codes"] = ["executable_unavailable"]
        return finish()

    environment = dict(os.environ, OMP_THREAD_LIMIT="1", LC_ALL="C")
    try:
        with tempfile.TemporaryDirectory(prefix="parcimonia-media-") as temporary:
            snapshot = Path(temporary) / "input.bin"
            snapshot.write_bytes(data)
            if time.monotonic() >= deadline:
                raise TimeoutError("deadline_exceeded")
            version_result = run_bounded(
                [str(tool), "-version"], deadline=deadline,
                max_stdout_bytes=8192, max_stderr_bytes=8192,
                cwd=temporary, env=environment,
            )
            report["native_calls"].append(_record("version", version_result))
            if not _usable(report, version_result):
                return finish()
            if version_result["started"] is not True:
                report["status"] = "failed"
                report["reason_codes"] = ["native_response_incomplete"]
                return finish()
            try:
                report["backend"]["version"] = _version(version_result)
            except (ValueError, UnicodeError):
                report["status"] = "failed"
                report["reason_codes"] = ["backend_version_unusable"]
                return finish()
            if time.monotonic() >= deadline:
                raise TimeoutError("deadline_exceeded")
            arguments = [
                str(tool), "-v", "error", "-protocol_whitelist", "file",
                "-f", profile["demuxer"], "-probesize", "1048576",
                "-analyzeduration", "1000000", "-max_probe_packets", "128",
            ]
            if profile["demuxer"] == "mov":
                arguments.extend(["-enable_drefs", "0", "-use_absolute_path", "0"])
            arguments.extend([
                "-show_entries", _ENTRIES, "-of", "json=string_validation=fail",
                "-i", str(snapshot),
            ])
            result = run_bounded(
                arguments, deadline=deadline, max_stdout_bytes=MAX_OUTPUT_BYTES,
                max_stderr_bytes=MAX_STDERR_BYTES, cwd=temporary, env=environment,
            )
            report["native_calls"].append(_record("probe", result))
            if not _usable(report, result):
                return finish()
            if result["started"] is not True:
                report["status"] = "failed"
                report["reason_codes"] = ["native_response_incomplete"]
                return finish()
            if _identity(tool, deadline) != before_hash:
                report["status"] = "failed"
                report["reason_codes"] = ["executable_identity_changed"]
                return finish()
            try:
                projection = parse_ffprobe_json(result["stdout"], expected_demuxer=profile["demuxer"])
                raw_json = result["stdout"].decode("utf-8")
            except (ValueError, UnicodeError):
                report["status"] = "failed"
                report["reason_codes"] = ["native_media_response_invalid"]
                return finish()
            if time.monotonic() >= deadline:
                raise TimeoutError("deadline_exceeded")
            report["status"] = "completed"
            report["raw_json"], report["projection"] = raw_json, projection
    except TimeoutError:
        report["status"] = "indeterminate"
        report["reason_codes"].append("deadline_exceeded")
    except _IdentityError as exc:
        report["status"] = "failed"
        report["reason_codes"].append(str(exc))
    except OSError:
        report["status"] = "failed"
        report["reason_codes"].append("local_probe_io_failed")
    except ValueError:
        report["status"] = "failed"
        report["reason_codes"].append("native_probe_configuration_unusable")
    finally:
        # Early unsuccessful returns still run context cleanup before this
        # measurement. A successful path also checks its deadline in finish.
        report["elapsed_ms"] = max(0.0, (time.monotonic() - started_at) * 1000)
    return finish()
