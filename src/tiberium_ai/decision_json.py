"""Canonical JSON for decision states and identities, without losing field names."""
from __future__ import annotations

import json
from typing import Any, Mapping

STATE_ENCODING_VERSION = "reflex-state/2"


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings.")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Preserve JSON types and Unicode; reject non-finite values and key coercion."""
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)
