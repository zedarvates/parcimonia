"""One explicit local text request for an existing caller, using JSON stdin.

The request requires schema_version=1, task_id, model and messages; max_tokens
and temperature are optional. Endpoint and timeout belong to process arguments.
The single JSON response is data only: no tools, shell, files or retries.

Usage: PYTHONPATH=src python3 examples/local_chat_worker.py < request.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, BinaryIO

from tiberium_ai.local_chat import _request, chat_completion
from tiberium_ai.local_probe import (
    _endpoint, _positive_number, _reject_constant, _unique_object,
)

MAX_REQUEST_BYTES = 262144
_REQUIRED = {"schema_version", "task_id", "model", "messages"}
_OPTIONAL = {"max_tokens", "temperature"}


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's usual errors can echo a supplied secret URL or value.
        raise ValueError("invalid process arguments")


def _read_request(stream: BinaryIO) -> dict[str, Any]:
    raw = stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("request exceeds the input byte limit")
    request = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if (not isinstance(request, dict) or not _REQUIRED <= request.keys()
            or request.keys() - _REQUIRED - _OPTIONAL):
        raise ValueError("request must use the supported envelope")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("unsupported request version")
    task_id = request["task_id"]
    if (not isinstance(task_id, str) or not task_id or task_id != task_id.strip()
            or len(task_id) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in task_id)):
        raise ValueError("invalid task identity")
    # Reuse the client's exact text-only validation, including its encoded cap.
    _request(
        request["model"], request["messages"],
        request.get("max_tokens", 1024), request.get("temperature", 0.0),
    )
    return request


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    parser.add_argument("--allow-lan", action="store_true")
    parser.add_argument("--timeout", type=float, default=180.0)
    try:
        args = parser.parse_args(argv)
        # Validate before reading or handing any request to the client.
        _endpoint(args.base_url, args.allow_lan)
        _positive_number(args.timeout, "timeout", 600)
        request = _read_request(sys.stdin.buffer)
        result = chat_completion(
            model=request["model"], messages=request["messages"],
            base_url=args.base_url, allow_lan=args.allow_lan, timeout=args.timeout,
            max_tokens=request.get("max_tokens", 1024),
            temperature=request.get("temperature", 0.0),
        )
        output = {**result, "task_id": request["task_id"]}
        # ASCII JSON also survives legacy Windows pipe encodings; json.loads
        # restores the original FR/EN and code characters without loss.
        print(json.dumps(output, ensure_ascii=True, separators=(",", ":"), allow_nan=False))
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        # Never echo request content, supplied arguments, credentials or errors.
        print("local completion configuration or input failed", file=sys.stderr)
        return 2
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
