"""Opt-in local OCR and embedded-PDF text extraction with bounded provenance.

Only a private snapshot is passed to a caller-selected native executable. The
executable and its reported version are observations, not authenticated origin,
an attestation of loaded weights, or an operating-system sandbox.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from typing import Any

from .media_probe import probe_media
from .native_process import run_bounded
from .text_evidence import parse_pdf_text, parse_tesseract_tsv
from .verification import hash_input

__all__ = ["extract_asset_text"]

MAX_INPUT_BYTES = 1024 * 1024
MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 262144
MAX_STDERR_BYTES = 32768
MAX_IMAGE_PIXELS = 4_000_000


class _IdentityError(ValueError):
    pass


def _text(value: Any, label: str) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 1024 or "\x00" in value:
        raise ValueError(f"{label} must be a nonempty trimmed UTF-8 string of at most 1024 characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8.") from exc


def _identity(path: Path, deadline: float) -> str:
    """Observe a bounded regular executable, checking detectable changes."""
    if time.monotonic() >= deadline:
        raise TimeoutError("deadline_exceeded")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_EXECUTABLE_BYTES:
            raise _IdentityError("executable_identity_unavailable")
        digest = hashlib.sha256()
        count = 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("deadline_exceeded")
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_EXECUTABLE_BYTES:
                raise _IdentityError("executable_identity_unavailable")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if signature(before) != signature(after) or signature(after) != signature(path.stat()):
        raise _IdentityError("executable_changed_during_identity")
    return digest.hexdigest()


def _record(phase: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": phase,
        "status": result["status"],
        "returncode": result["returncode"],
        "stdout_sha256": hashlib.sha256(result["stdout"]).hexdigest(),
        "stderr_sha256": hashlib.sha256(result["stderr"]).hexdigest(),
        "stdout_complete": result["stdout_complete"],
        "stderr_complete": result["stderr_complete"],
        "elapsed_ms": result["elapsed_ms"],
        "started": result["started"],
        "error": result["error"],
    }


def _usable(report: dict[str, Any], result: dict[str, Any]) -> bool:
    if result["status"] in {"timeout", "output_limit"}:
        report["status"] = "indeterminate"
        report["reason_codes"].append("native_" + result["status"])
    elif result["status"] == "failed_to_start":
        report["status"] = "unavailable"
        report["reason_codes"].append("native_start_failed")
    elif (
        result["status"] != "completed" or result["error"] is not None
        or result["stdout_complete"] is not True or result["stderr_complete"] is not True
    ):
        report["status"] = "failed"
        report["reason_codes"].append("native_response_incomplete")
    elif result["returncode"] != 0:
        report["status"] = "failed"
        report["reason_codes"].append("native_exit_nonzero")
    else:
        return True
    return False


def _version(backend: str, result: dict[str, Any]) -> str:
    pattern = r"tesseract v?([0-9]+)\.[0-9A-Za-z.+_-]+" if backend == "tesseract" else r"pdftotext version ([0-9]+)\.[0-9A-Za-z.+_-]+"
    candidates = (result["stdout"] + b"\n" + result["stderr"]).decode("utf-8").splitlines()
    for line in candidates[:16]:
        line = line.strip()
        match = re.fullmatch(pattern, line) if len(line) <= 256 else None
        if match:
            if backend == "tesseract" and int(match.group(1)) < 4:
                raise ValueError("unsupported_tesseract_version")
            return line
    raise ValueError("unrecognized_backend_version")


def extract_asset_text(
    data: bytes, *, filename: str, source_id: str, revision: str, backend: str,
    executable: str | None = None, language: str = "eng", max_pages: int = 3,
    timeout_s: float = 10.0, complete: bool = True,
) -> dict[str, Any]:
    """Extract text from a complete supported sample, with no implicit fallback.

    Invalid caller arguments raise ValueError. Missing tools, unsupported input,
    native failures and unusable responses return distinct non-success reports.
    One absolute deadline covers identity, preflight, snapshot and extraction.
    """
    started_at = time.monotonic()
    if type(data) is not bytes or len(data) > MAX_INPUT_BYTES:
        raise ValueError("data must be bytes of at most one MiB.")
    for label, value in (("filename", filename), ("source_id", source_id), ("revision", revision)):
        _text(value, label)
    if type(backend) is not str or backend not in {"tesseract", "pdftotext"}:
        raise ValueError("backend must be tesseract or pdftotext.")
    if executable is not None:
        _text(executable, "executable")
    if type(language) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z_]{0,31}", language) or language.lower() == "osd":
        raise ValueError("language must be one simple OCR language label, excluding osd.")
    if type(max_pages) is not int or not 1 <= max_pages <= 8:
        raise ValueError("max_pages must be an integer from one to eight.")
    if type(timeout_s) not in (int, float) or not 0 < timeout_s <= 30 or not math.isfinite(timeout_s):
        raise ValueError("timeout_s must be a finite number greater than zero and at most 30.")
    if type(complete) is not bool:
        raise ValueError("complete must be a boolean.")
    timeout_s = float(timeout_s)
    deadline = started_at + timeout_s
    digest = hashlib.sha256(data).hexdigest()
    source = {"id": source_id, "revision": revision, "filename": filename}
    request = {
        "source": source, "sample_sha256": digest, "complete": complete,
        "backend": backend, "executable_requested": executable, "language": language,
        "max_pages": max_pages, "timeout_s": timeout_s,
    }
    report: dict[str, Any] = {
        "schema": "parcimonia.asset-text-extraction/v1",
        "source": source, "input_hash": hash_input(request),
        "sample_sha256": digest, "source_complete": complete,
        "backend": {"id": backend, "version": None, "executable": None, "executable_sha256": None, "language": language if backend == "tesseract" else None, "weights_hash": None},
        "status": "indeterminate", "text": None, "evidence": [], "coverage": None,
        "reason_codes": [], "native_calls": [], "elapsed_ms": 0.0,
        "limits": {
            "max_input_bytes": MAX_INPUT_BYTES, "max_stdout_bytes": MAX_OUTPUT_BYTES,
            "max_stderr_bytes": MAX_STDERR_BYTES, "max_image_pixels": MAX_IMAGE_PIXELS,
            "quality": "not_qualified", "os_sandbox": "not_provided",
            "weights": "not_attested", "fallback": "none", "ocr_scores": "uncalibrated",
            "native_inference": "local_ocr" if backend == "tesseract" else "embedded_text_extraction",
            "executable_identity": "observed_before_and_after_not_atomic_or_authenticated",
        },
    }

    def finish() -> dict[str, Any]:
        now = time.monotonic()
        if report["status"] == "completed" and now >= deadline:
            report["status"] = "indeterminate"
            report["reason_codes"].append("deadline_exceeded")
        if report["status"] != "completed":
            report["text"], report["evidence"], report["coverage"] = None, [], None
        report["elapsed_ms"] = max(0.0, (now - started_at) * 1000)
        report["reason_codes"] = sorted(set(report["reason_codes"]))
        return report

    if not complete:
        report["reason_codes"] = ["complete_source_required"]
        return finish()
    width = height = None
    suffix = ".pdf"
    if backend == "tesseract":
        probe = probe_media(data, complete=True)
        if probe is None or probe["format"] not in {"png", "jpeg"}:
            report["reason_codes"] = ["unsupported_image_format"]
            return finish()
        values = {item["name"]: item["value"] for item in probe["metadata"]}
        width, height = values.get("width"), values.get("height")
        if probe["issues"] or type(width) is not int or type(height) is not int:
            report["reason_codes"] = ["image_header_unusable"]
            return finish()
        if width * height > MAX_IMAGE_PIXELS:
            report["reason_codes"] = ["image_pixel_budget_exceeded"]
            return finish()
        suffix = ".png" if probe["format"] == "png" else ".jpg"
    elif not data.startswith(b"%PDF-"):
        report["reason_codes"] = ["unsupported_pdf_signature"]
        return finish()

    selected = executable if executable is not None else shutil.which(backend)
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
        with tempfile.TemporaryDirectory(prefix="parcimonia-text-") as temporary:
            snapshot = Path(temporary) / ("input" + suffix)
            snapshot.write_bytes(data)
            if time.monotonic() >= deadline:
                raise TimeoutError("deadline_exceeded")
            version_result = run_bounded(
                [str(tool), "--version" if backend == "tesseract" else "-v"],
                deadline=deadline, max_stdout_bytes=8192, max_stderr_bytes=8192,
                cwd=temporary, env=environment,
            )
            report["native_calls"].append(_record("version", version_result))
            if not _usable(report, version_result):
                return finish()
            try:
                report["backend"]["version"] = _version(backend, version_result)
            except (ValueError, UnicodeError):
                report["status"] = "failed"
                report["reason_codes"] = ["backend_version_unusable"]
                return finish()
            if time.monotonic() >= deadline:
                raise TimeoutError("deadline_exceeded")
            if backend == "tesseract":
                arguments = [str(tool), str(snapshot), "stdout", "-l", language, "--oem", "1", "--psm", "6", "tsv"]
            else:
                arguments = [str(tool), "-f", "1", "-l", str(max_pages), "-enc", "UTF-8", "-eol", "unix", str(snapshot), "-"]
            result = run_bounded(arguments, deadline=deadline, max_stdout_bytes=MAX_OUTPUT_BYTES, max_stderr_bytes=MAX_STDERR_BYTES, cwd=temporary, env=environment)
            report["native_calls"].append(_record("extract", result))
            if not _usable(report, result):
                return finish()
            if _identity(tool, deadline) != before_hash:
                report["status"] = "failed"
                report["reason_codes"] = ["executable_identity_changed"]
                return finish()
            try:
                parsed = parse_tesseract_tsv(result["stdout"], width=width, height=height) if backend == "tesseract" else parse_pdf_text(result["stdout"], max_pages=max_pages)
            except (ValueError, UnicodeError):
                report["status"] = "failed"
                report["reason_codes"] = ["native_text_response_invalid"]
                return finish()
            if time.monotonic() >= deadline:
                raise TimeoutError("deadline_exceeded")
            report["status"] = "completed"
            report["text"] = parsed["text"]
            report["evidence"] = parsed["evidence"]
            report["coverage"] = parsed["coverage"]
            report["limits"]["parser_limitations"] = parsed["limitations"]
            if not parsed["text"].strip():
                report["reason_codes"].append("no_text_extracted")
    except TimeoutError:
        report["status"] = "indeterminate"
        report["reason_codes"].append("deadline_exceeded")
    except _IdentityError as exc:
        report["status"] = "failed"
        report["reason_codes"].append(str(exc))
    except OSError:
        report["status"] = "failed"
        report["reason_codes"].append("local_extraction_io_failed")
    finally:
        # Early returns inside the context still include its cleanup time.
        report["elapsed_ms"] = max(0.0, (time.monotonic() - started_at) * 1000)
    return finish()
