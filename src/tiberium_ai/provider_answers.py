"""Normalize SystemOne wire answers at their declared serialization precision."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .reflex import ReflexKind, ReflexQuestion

NORMALIZER_VERSION = "systemone-answers/1"


def normalize_systemone_answers(
    raw: Mapping[str, Any], questions: Sequence[ReflexQuestion], *,
    probability_decimals: int = 4, preserve_noul_confidence: bool = False,
) -> dict[str, dict[str, Any]]:
    """Return new answer dictionaries; keep the provider's original trace intact.

    Core Reflex validation stays strict. Only a provider adapter may use this
    bounded rounding tolerance, with a precision fixed by its wire contract.
    """
    if type(probability_decimals) is not int or not 0 <= probability_decimals <= 15:
        raise ValueError("invalid probability serialization precision")
    names = [q.name for q in questions]
    if not names or len(set(names)) != len(names):
        raise ValueError("nonempty unique questions required")
    if not isinstance(raw, Mapping) or set(raw) != set(names):
        raise ValueError("incomplete or extra answers")
    answers = {}
    for q in questions:
        if not isinstance(raw[q.name], Mapping):
            raise ValueError("invalid answer")
        a = dict(raw[q.name])
        if a.get("type") != q.kind.value:
            raise ValueError("answer type mismatch")
        if q.kind == ReflexKind.NOUL:
            p = a.get("noul")
            if not _probability(p):
                raise ValueError("invalid noul probability")
            a["probabilities"] = {"false": 1 - p, "true": p}
            if not preserve_noul_confidence:
                a["confidence"] = None
        else:
            probs = a.get("probabilities")
            wire_keys = tuple(str(i) for i in range(len(q.option_keys))) if q.kind == ReflexKind.SCORE else q.option_keys
            if not isinstance(probs, Mapping) or set(probs) != set(wire_keys):
                raise ValueError("invalid probability keys")
            values = [probs[key] for key in wire_keys]
            if any(not _probability(p) for p in values):
                raise ValueError("invalid probabilities")
            total = math.fsum(values)
            tolerance = len(values) * .5 * 10 ** -probability_decimals + 1e-10
            if total <= 0 or abs(total - 1) > tolerance:
                raise ValueError("probabilities exceed rounding tolerance")
            a["probabilities"] = {key: p / total for key, p in zip(q.option_keys, values)}
        answers[q.name] = a
    return answers


def _probability(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and 0 <= value <= 1)
