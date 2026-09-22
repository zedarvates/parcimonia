"""Measure candidate mechanisms on real asks, without inventing a single label.

Real asks have no labels: nobody has said what each of them needed. So this lane
measures only what labels cannot change.

* coverage: does a mechanism answer at all, and how often does it abstain
* what it answers with: the distribution of actions over real traffic
* agreement between mechanisms: where several independent ones name the same
  action, and where they split

Agreement is a triage signal, never a truth. Where three mechanisms agree the case
is probably easy; where they split, one human label buys the most information.
That is how the labelling cost of a real corpus is estimated instead of guessed.

The retrieval candidate is deliberately absent from this lane. It needs labelled
examples to retrieve from, and there are none for real asks, which is exactly the
bottleneck this measurement is here to quantify.

The declared kinds are the actions the verb lexicon can express, and their hints
are the verbs that reach them. That is an artefact, not a discovery, and it is
reported as one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .signature_backends import VERB_LEXICON
from .signature_taxonomy import STOPWORDS
from .task_signature import (
    DeclaredItem,
    SignatureSchema,
    predict_signature,
)
from .signature_backends import normalise_text, tokens_of

__all__ = [
    "LABELS_ABSENT",
    "CandidateReport",
    "agreement_triage",
    "looks_like_a_verb",
    "measure_coverage",
    "reachable_schema",
    "unreached_verb_candidates",
]

#: Endings that carry the infinitive in French, plus the two English ones worth
#: keeping. This is morphology by shape, not a part-of-speech analysis: no tagger,
#: no weights, and the output is a proposal a human ratifies.
_INFINITIVE_ENDINGS: tuple[str, ...] = ("er", "ir", "re")

#: A capitalised word, which is how a project or product name shows up. A verb
#: candidate and a domain term are different lists, and one token can be a false
#: verb and a true piece of vocabulary at the same time: "Odycer" ends like an
#: infinitive and is the name of a project.
_CAPITALISED = re.compile(r"\b([A-Z][A-Za-z0-9_-]{2,})\b")

#: Paths are stripped before the census, and only there: the corpus keeps what
#: was written, while an analysis declares its preprocessing. Without this, a
#: path contributes fragments such as appdata, local, temp or a hyphenated
#: project name, which are environment rather than vocabulary.
_PATH_LIKE = re.compile(
    r"(?:[A-Za-z]:\\[^\s\"']+|/(?:[^\s/]+/)+[^\s/]*)"
)

#: Why this lane cannot authorize anything, stated once for every report.
LABELS_ABSENT = (
    "no outcome label exists for real asks: coverage and agreement are measurable, "
    "accuracy is not"
)


def reachable_schema(name: str = "real-asks") -> SignatureSchema:
    """Declare one kind per action the lexicon can express, hints included."""
    hints: dict[str, list[str]] = {}
    for verb, action in VERB_LEXICON.items():
        hints.setdefault(action, []).append(verb)
    kinds = tuple(
        DeclaredItem(action, tuple(sorted(set(verbs))))
        for action, verbs in sorted(hints.items())
    )
    if len(kinds) < 2:
        raise ValueError("the lexicon must express at least two actions.")
    return SignatureSchema(name=name, kinds=kinds)


@dataclass(frozen=True)
class CandidateReport:
    """What one mechanism does on a corpus of real asks."""

    predictor: str
    distinct: int
    volume: int
    answered_distinct: int
    answered_volume: int
    actions: Mapping[str, int]
    by_band: Mapping[str, Mapping[str, int]]

    @property
    def coverage_distinct(self) -> float:
        return self.answered_distinct / self.distinct if self.distinct else 0.0

    @property
    def coverage_volume(self) -> float:
        return self.answered_volume / self.volume if self.volume else 0.0

    def to_record(self) -> dict[str, Any]:
        return {
            "predictor": self.predictor,
            "distinct": self.distinct,
            "volume": self.volume,
            "answered_distinct": self.answered_distinct,
            "answered_volume": self.answered_volume,
            "coverage_distinct": round(self.coverage_distinct, 4),
            "coverage_volume": round(self.coverage_volume, 4),
            "actions": dict(sorted(self.actions.items())),
            "by_band": {band: dict(counts) for band, counts in self.by_band.items()},
        }


def _band(chars: int) -> str:
    if chars < 30:
        return "short<30"
    if chars < 100:
        return "30-99"
    if chars < 300:
        return "100-299"
    if chars < 1000:
        return "300-999"
    return "1000+"


def looks_like_a_verb(token: str) -> bool:
    """Return whether a token has the shape of a verb worth proposing.

    Deliberately narrow: an ending in er, ir or re on a token of at least four
    characters. Broader shapes such as a trailing e were rejected because French
    nouns and adjectives share them, and a proposal that is mostly noise is worse
    than a short one. An English base form carries no ending to read at all, which
    is why the census also uses position: "add a note" is caught by its first
    token, not by its shape.
    """
    if not isinstance(token, str):
        raise TypeError("token must be a string.")
    if len(token) < 4:
        return False
    return token.endswith(_INFINITIVE_ENDINGS)


def unreached_verb_candidates(
    asks: Sequence[Mapping[str, Any]],
    *,
    predictors: Mapping[str, Any],
    schema: SignatureSchema | None = None,
    min_count: int = 5,
    top: int = 15,
) -> dict[str, Any]:
    """Census the verbs of the asks no mechanism reaches.

    Two signals are counted, both declared rather than inferred: the first token
    of an imperative ask, and any token whose shape is an infinitive. Each is then
    split into what the lexicon already knows and what it misses, because the gap
    is the only part an artefact has to fill.

    A third list carries what is neither a verb nor noise: the capitalised words,
    which are domain vocabulary and belong in a hint set rather than in a verb
    lexicon. Mixing the two lists is how a project name gets discarded as a false
    verb instead of being declared as a term.
    """
    declared = [entry for entry in asks if isinstance(entry, Mapping)]
    if not declared:
        raise ValueError("at least one ask is required.")
    if not predictors:
        raise ValueError("at least one predictor is required.")
    if type(min_count) is not int or min_count < 1:
        raise ValueError("min_count must be a positive integer.")
    active = schema or reachable_schema()

    unreached: list[Mapping[str, Any]] = []
    for entry in declared:
        text = str(entry.get("text", ""))
        votes = [
            _predict(active, text, predictor, label)
            for label, predictor in predictors.items()
        ]
        if all(vote is None for vote in votes):
            unreached.append(entry)

    prepared: list[tuple[int, tuple[str, ...], str]] = []
    for entry in unreached:
        weight = int(entry.get("count", 1))
        raw_text = _PATH_LIKE.sub(" ", str(entry.get("text", "")))
        # The raw text is kept beside the tokens: normalising lowercases, and the
        # capital is the only signal that separates a name from a verb.
        prepared.append((weight, tokens_of(raw_text), raw_text))

    # Two passes, so the rule does not depend on the order the corpus arrives in:
    # whatever is written with a capital somewhere is a name, and a name is not a
    # verb candidate anywhere. "Odycer" and "auditer" have the same shape, and the
    # capital is the only thing that separates them.
    named: set[str] = set()
    capitalised: dict[str, int] = {}
    for weight, _tokens, raw_text in prepared:
        for match in _CAPITALISED.finditer(raw_text):
            # Only a capital at position zero is a sentence opening; anywhere else
            # it names something. Dropping the first match by rank instead of by
            # position silently discarded a name written mid-text.
            if match.start() == 0:
                continue
            raw_word = match.group(1)
            term = normalise_text(raw_word)
            if len(term) < 4 or term in STOPWORDS or term in VERB_LEXICON:
                continue
            named.add(term)
            capitalised[term] = capitalised.get(term, 0) + weight

    first_tokens: dict[str, int] = {}
    shaped: dict[str, int] = {}
    for weight, tokens, _raw_text in prepared:
        if tokens:
            head = tokens[0]
            if head not in STOPWORDS and len(head) >= 3:
                first_tokens[head] = first_tokens.get(head, 0) + weight
        for token in set(tokens):
            if token in STOPWORDS or token in named:
                continue
            if not looks_like_a_verb(token):
                continue
            shaped[token] = shaped.get(token, 0) + weight

    def split(counts: Mapping[str, int]) -> dict[str, Any]:
        known = {
            term: weight
            for term, weight in counts.items()
            if term in VERB_LEXICON
        }
        missing = {
            term: weight
            for term, weight in counts.items()
            if term not in VERB_LEXICON and weight >= min_count
        }
        ranked = sorted(missing.items(), key=lambda pair: (-pair[1], pair[0]))
        return {
            "already_declared": len(known),
            "declared_volume": sum(known.values()),
            "missing_distinct": len(missing),
            "missing_volume": sum(missing.values()),
            "missing_top": [
                {"term": term, "weight": weight} for term, weight in ranked[:top]
            ],
        }

    return {
        "asks": len(declared),
        "unreached_distinct": len(unreached),
        "unreached_volume": sum(int(entry.get("count", 1)) for entry in unreached),
        "by_first_token": split(first_tokens),
        "by_shape": split(shaped),
        "by_domain_term": {
            "distinct": len(capitalised),
            "volume": sum(capitalised.values()),
            "top": [
                {"term": term, "weight": weight}
                for term, weight in sorted(
                    (
                        (term, weight)
                        for term, weight in capitalised.items()
                        if weight >= min_count
                    ),
                    key=lambda pair: (-pair[1], pair[0]),
                )[:top]
            ],
        },
        "needs_ratification": True,
        "reading": (
            "verbs proposed by position and by shape, not by a tagger; the caller "
            "declares them, and they must be measured on asks this census was not "
            "taken from"
        ),
    }


def _predict(
    schema: SignatureSchema, prompt: str, predictor: Any, label: str
) -> str | None:
    signature = predict_signature(
        schema,
        prompt,
        predictor=predictor,
        predictor_id=label,
        predictor_version="1",
    )
    return None if signature.abstained else signature.kind


def measure_coverage(
    prompts: Sequence[Mapping[str, Any]],
    *,
    predictors: Mapping[str, Any],
    schema: SignatureSchema | None = None,
) -> tuple[CandidateReport, ...]:
    """Report what each mechanism answers on a corpus of real asks."""
    declared = [entry for entry in prompts if isinstance(entry, Mapping)]
    if not declared:
        raise ValueError("at least one prompt is required.")
    if not predictors:
        raise ValueError("at least one predictor is required.")
    active = schema or reachable_schema()

    reports: list[CandidateReport] = []
    for label, predictor in predictors.items():
        answered_distinct = 0
        answered_volume = 0
        actions: dict[str, int] = {}
        bands: dict[str, dict[str, int]] = {}
        for entry in declared:
            count = int(entry.get("count", 1))
            band = bands.setdefault(_band(len(str(entry.get("text", "")))), {"total": 0, "answered": 0})
            band["total"] += count
            kind = _predict(active, str(entry.get("text", "")), predictor, label)
            if kind is None:
                continue
            answered_distinct += 1
            answered_volume += count
            band["answered"] += count
            actions[kind] = actions.get(kind, 0) + count
        reports.append(
            CandidateReport(
                predictor=label,
                distinct=len(declared),
                volume=sum(int(entry.get("count", 1)) for entry in declared),
                answered_distinct=answered_distinct,
                answered_volume=answered_volume,
                actions=actions,
                by_band=bands,
            )
        )
    return tuple(reports)


def agreement_triage(
    prompts: Sequence[Mapping[str, Any]],
    *,
    predictors: Mapping[str, Any],
    schema: SignatureSchema | None = None,
) -> dict[str, Any]:
    """Split real asks by how many mechanisms agree, to price the labelling.

    Unanimous cases are the ones a later pipeline could handle without asking
    anyone. Split cases are where one human label buys the most. Insufficient
    cases are answered by fewer than two mechanisms, so no comparison exists.
    """
    declared = [entry for entry in prompts if isinstance(entry, Mapping)]
    if not declared:
        raise ValueError("at least one prompt is required.")
    if len(predictors) < 2:
        raise ValueError("agreement needs at least two predictors.")
    active = schema or reachable_schema()

    buckets: dict[str, dict[str, int]] = {
        name: {"distinct": 0, "volume": 0}
        for name in ("unanimous", "majority", "split", "insufficient")
    }
    examples: dict[str, list[str]] = {name: [] for name in buckets}
    for entry in declared:
        text = str(entry.get("text", ""))
        count = int(entry.get("count", 1))
        votes = [
            _predict(active, text, predictor, label)
            for label, predictor in predictors.items()
        ]
        answered = [vote for vote in votes if vote is not None]
        if len(answered) < 2:
            family = "insufficient"
        elif len(set(answered)) == 1:
            family = "unanimous"
        elif max(answered.count(vote) for vote in set(answered)) >= 2:
            family = "majority"
        else:
            family = "split"
        buckets[family]["distinct"] += 1
        buckets[family]["volume"] += count
        if family in ("unanimous", "split") and len(examples[family]) < 3:
            examples[family].append(str(entry.get("id", "")))

    total = sum(bucket["volume"] for bucket in buckets.values())
    return {
        "buckets": buckets,
        "total_volume": total,
        "unanimous_share": round(buckets["unanimous"]["volume"] / total, 4) if total else 0.0,
        "needs_a_label_share": round(
            (buckets["split"]["volume"] + buckets["majority"]["volume"]) / total, 4
        )
        if total
        else 0.0,
        "example_ids": examples,
        "reading": LABELS_ABSENT,
    }
