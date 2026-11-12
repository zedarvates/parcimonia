"""Read only explicitly catalogued, pinned local knowledge text files.

No directory scan, source write, URL read, model or synchronization runs. Pins
bind raw bytes, not truth, authenticity or freshness. Declared metadata remains
unchanged. The caller owns the root and its parents: component checks and the
bounded consistency reader do not sandbox a hostile filesystem owner.
"""

from __future__ import annotations

import hashlib
import ntpath
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any

from .asset_cli import _read_regular
from .knowledge_crosswalk import MAX_INDEX_BYTES
from .knowledge_import import _json_budget, _object, _text
from .verification import hash_input

__all__ = ["CATALOG_SCHEMA", "EXPORT_SCHEMA", "export_local_documents"]

CATALOG_SCHEMA = "parcimonia.local-knowledge-catalog/v1"
EXPORT_SCHEMA = "parcimonia.local-knowledge-export-report/v1"
_FIELDS = {"id", "file", "sha256", "version", "project", "uri", "timestamp", "state"}
_STATES = frozenset({"active", "superseded", "rejected", "paused"})
_SUFFIXES = frozenset({".md", ".txt", ".jsonl"})
_MAX_FILES = 64
_MAX_FILE_BYTES = 65536


def _reparse_point(info: os.stat_result) -> bool:
    # NTFS junctions can look like directories to S_ISDIR while redirecting
    # lookup elsewhere. Refuse every reparse point, including placeholders.
    return bool(getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _relative_path(value: Any) -> tuple[str, ...]:
    _text(value, "document.file", maximum=4096, identity=True)
    if (value.startswith("/") or "\\" in value or ntpath.splitdrive(value)[0]
            or any(part in {"", ".", ".."} or ":" in part for part in value.split("/"))):
        raise ValueError("file must be a strict relative POSIX path without traversal or a drive.")
    if PurePosixPath(value).suffix.lower() not in _SUFFIXES:
        raise ValueError("Only .md, .txt and .jsonl text files are supported.")
    return tuple(value.split("/"))


def export_local_documents(catalog: Any, *, root: str | Path) -> dict[str, Any]:
    """Read a closed allowlist and return an import-compatible document response.

    Every source must have the caller's exact lowercase SHA-256 pin. An error
    refuses the export instead of reporting a partial corpus as complete. UTF-8
    decoding preserves original text, including line endings and a BOM. JSONL
    files are text sources; their rows are neither parsed nor executed.
    """
    _json_budget(catalog, maximum=MAX_INDEX_BYTES, label="local catalog")
    _object(catalog, {"schema", "documents"}, "local catalog")
    if type(catalog["schema"]) is not str or catalog["schema"] != CATALOG_SCHEMA:
        raise ValueError("Unsupported local-knowledge catalog schema.")
    entries = catalog["documents"]
    if type(entries) is not list or len(entries) > _MAX_FILES:
        raise ValueError("Local catalog must contain at most 64 documents.")
    selected = []
    seen_ids, seen_paths = set(), set()
    # Validate the entire allowlist before opening any selected source.
    for entry in entries:
        _object(entry, _FIELDS, "local document")
        for field in ("id", "version", "project"):
            _text(entry[field], "document." + field, maximum=256, identity=True)
        _text(entry["uri"], "document.uri", maximum=2048, identity=True)
        _text(entry["timestamp"], "document.timestamp", maximum=1024, identity=True)
        digest = entry["sha256"]
        if (type(digest) is not str or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("sha256 must be a lowercase 64-character hexadecimal digest.")
        if type(entry["state"]) is not str or entry["state"] not in _STATES:
            raise ValueError("Unsupported declared document state.")
        parts = _relative_path(entry["file"])
        path_key = os.path.normcase(entry["file"])
        if entry["id"] in seen_ids or path_key in seen_paths:
            raise ValueError("Local document IDs and paths must be unique.")
        seen_ids.add(entry["id"])
        seen_paths.add(path_key)
        selected.append((entry, parts))
    if not isinstance(root, (str, Path)) or not str(root):
        raise ValueError("root must be an explicit directory path.")
    base = Path(root)
    base_info = base.lstat()
    if not stat.S_ISDIR(base_info.st_mode) or _reparse_point(base_info):
        raise ValueError("root must be an existing directory, not a link.")
    documents, files = [], []
    total_bytes = 0
    for entry, parts in sorted(selected, key=lambda pair: pair[0]["id"]):
        path = base
        for number, part in enumerate(parts):
            path = path / part
            info = path.lstat()
            wanted = stat.S_ISREG if number == len(parts) - 1 else stat.S_ISDIR
            if not wanted(info.st_mode) or _reparse_point(info):
                raise ValueError("Every source component must be a non-link directory or regular file.")
        raw, observed_size, complete = _read_regular(str(path), _MAX_FILE_BYTES)
        if not complete:
            raise ValueError("Selected text file exceeds 64 KiB.")
        actual = hashlib.sha256(raw).hexdigest()
        if actual != entry["sha256"]:
            raise ValueError("Selected text file does not match its declared raw SHA-256 pin.")
        # The byte pin is checked before UTF-8 decoding; no newline conversion.
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Selected text file must be valid UTF-8.") from exc
        total_bytes += len(raw)
        if total_bytes > MAX_INDEX_BYTES:
            raise ValueError("Selected text exceeds the 2 MiB export budget.")
        documents.append({
            **{field: entry[field] for field in ("id", "version", "project", "uri", "timestamp", "state")},
            "text": text,
        })
        files.append({"id": entry["id"], "file": entry["file"],
                      "sha256": actual, "size_bytes": observed_size})
    response = {"documents": documents}
    result = {
        "schema": EXPORT_SCHEMA, "documents": response,
        "manifest": {"files": files, "file_count": len(files),
                     "documents_hash": hash_input(response)},
    }
    _json_budget(result, maximum=MAX_INDEX_BYTES, label="local export")
    return result
