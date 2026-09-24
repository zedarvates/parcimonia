"""Experimental action/object retrieval over labelled signature memories.

The same answer averaging and abstention policy as KnnSignatureBackend are
retained. Only neighbour scoring changes; labels never tune the similarity.
This remains a fixture candidate until independent outcomes are available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .signature_backends import (
    KnnSignatureBackend,
    SignatureMemoryEntry,
    VERB_LEXICON,
    tokens_of,
    _no_answer,
)

__all__ = ["SpanKnnSignatureBackend", "frame_parts"]

_BREAKS = frozenset(
    {"before", "after", "then", "and", "puis", "ensuite", "avant", "apres"}
)
_FILLER = frozenset(
    {"a", "an", "the", "this", "that", "of", "to", "in", "on", "at", "de", "du", "des", "la", "le", "les", "ce"}
)


def frame_parts(text: str) -> tuple[str | None, frozenset[str]]:
    """Read the first declared action and the adjacent object tokens."""
    tokens = tokens_of(text)
    for index, token in enumerate(tokens):
        action = VERB_LEXICON.get(token)
        if action is None:
            continue
        end = next(
            (i for i in range(index + 1, len(tokens)) if tokens[i] in _BREAKS),
            len(tokens),
        )
        obj = frozenset(
            item for item in tokens[index + 1 : end] if item not in _FILLER
        )
        return action, obj
    return None, frozenset()


def _similarity(left: str, right: str) -> float:
    left_action, left_object = frame_parts(left)
    right_action, right_object = frame_parts(right)
    if left_action is None or right_action is None or left_action != right_action:
        return 0.0
    if left_object == right_object:
        return 1.0
    if not left_object or not right_object:
        return 0.0
    overlap = len(left_object & right_object) / len(left_object | right_object)
    return 0.5 + 0.5 * overlap if overlap else 0.0


@dataclass(frozen=True)
class SpanKnnSignatureBackend:
    memory: tuple[SignatureMemoryEntry, ...]
    k: int = 3
    min_similarity: float = 0.2
    latin_only: bool = False

    def __post_init__(self) -> None:
        # Reuse the validated parameter contract of the token KNN.
        KnnSignatureBackend(self.memory, self.k, self.min_similarity)

    def neighbours(
        self, state_text: str
    ) -> tuple[tuple[float, SignatureMemoryEntry], ...]:
        scored = [
            (score, entry)
            for entry in self.memory
            if (score := _similarity(state_text, entry.prompt)) >= self.min_similarity
            and score > 0.0
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].case_id))
        return tuple(scored[: self.k])

    def evaluate(
        self, state_text: str, questions: Sequence[Any]
    ) -> Mapping[str, Mapping[str, Any]]:
        neighbours = self.neighbours(state_text)
        token_backend = KnnSignatureBackend(
            self.memory, self.k, self.min_similarity
        )
        if not neighbours:
            # No match means the same honest unknown as the baseline.
            return {question.name: _no_answer(question) for question in questions}
        return {
            question.name: token_backend._average(question, neighbours)
            for question in questions
        }
