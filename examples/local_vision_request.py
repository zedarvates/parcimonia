"""Prepare one explicit vision request; no inference, networking or file writes.

Only caller-named regular PNG/JPEG files are read. Image headers are inspected
by the existing client; this does not decode pixels or prove image quality.
Pipe stdout into local_chat_worker.py to request inference separately.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Sequence

from tiberium_ai.local_chat import (
    MAX_IMAGE_BYTES, MAX_IMAGES, MAX_VISION_REQUEST_BYTES, _identifier, _request,
)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse can otherwise repeat private paths, prompts or model IDs.
        raise ValueError("invalid process arguments")


def _read_image(filename: str) -> tuple[str, bytes]:
    path = Path(filename).absolute()
    # Check lexical ancestors in order, without resolving away symbolic links.
    for ancestor in reversed(path.parents):
        if ancestor.is_symlink():
            raise ValueError("symbolic links are unsupported")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_IMAGE_BYTES:
        raise ValueError("image must be a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or opened.st_size > MAX_IMAGE_BYTES):
            raise ValueError("image changed before reading")
        raw = stream.read(MAX_IMAGE_BYTES + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    observed = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if (len(raw) > MAX_IMAGE_BYTES or not stat.S_ISREG(current.st_mode)
            or observed(before) != observed(opened)
            or observed(opened) != observed(after)
            or observed(after) != observed(current)):
        raise ValueError("image changed while reading")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", raw
    if raw.startswith(b"\xff\xd8"):
        return "image/jpeg", raw
    raise ValueError("image must have a PNG or JPEG signature")


def build_request(
    *, task_id: str, model: str, prompt: str, image_paths: Sequence[str],
    max_tokens: int = 1024, temperature: float = 0.0,
) -> dict[str, Any]:
    """Read explicit images and return a client-validated schema-v2 request.

    File identity/change checks are observations, not a filesystem sandbox or
    an atomic snapshot against concurrent writers. No image path is exported.
    """
    _identifier(task_id)
    _identifier(model)
    if (isinstance(image_paths, (str, bytes))
            or not 1 <= len(image_paths) <= MAX_IMAGES):
        raise ValueError("one or two explicit image paths are required")
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for filename in image_paths:
        mime_type, raw = _read_image(filename)
        parts.append({"type": "image_url", "image_url": {
            "url": f"data:{mime_type};base64," + base64.b64encode(raw).decode("ascii"),
        }})
    messages = [{"role": "user", "content": parts}]
    _request(model, messages, max_tokens, temperature, request_schema_version=2)
    request = {
        "schema_version": 2, "task_id": task_id, "model": model,
        "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
    }
    # The worker consumes the envelope, not only the API body. Account for ASCII
    # escaping too, so stdout can always be read under the worker's byte budget.
    encoded = json.dumps(request, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("ascii")) + 1 > MAX_VISION_REQUEST_BYTES:
        raise ValueError("request envelope exceeds the worker byte budget")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--image", action="append", required=True)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    try:
        args = parser.parse_args(argv)
        request = build_request(
            task_id=args.task_id, model=args.model, prompt=args.prompt,
            image_paths=args.image, max_tokens=args.max_tokens, temperature=args.temperature,
        )
        encoded = json.dumps(request, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        print(encoded)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        print("local vision request preparation failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
