"""Read a real corpus: what carries an ask, what carries several, what vocabulary.

Three questions are answered here, all of them by counting rather than by
guessing, and all of them before any mechanism is chosen.

* Which entries carry an ask at all? Roughly half of a real message volume turns
  out to be continuations whose content lives in the conversation, not in the
  text. That half is not a predictor problem, it is a state problem.
* Which entries carry more than one piece of work? A prompt that holds several
  tasks is the precondition for any decomposition, so it is measured before that
  work is worth starting.
* Which vocabulary does the caller actually use? The share of asks that no
  declared hint reaches is the number that says what a taxonomy is missing, and
  the candidate hints proposed here are drawn from the corpus itself.

One rule keeps the third question honest: an artefact derived from a corpus must
be measured on prompts it was not derived from. Proposing hints from words that
will later be scored with those same words is how a vocabulary ends up
describing itself. The proposal is therefore a proposal, marked as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .signature_backends import VERB_LEXICON, tokens_of

__all__ = [
    "CONTINUATION_TERMS",
    "RESPONSIBILITY",
    "STOPWORDS",
    "classify_prompt",
    "multi_ask_candidates",
    "partition_prompts",
    "propose_taxonomy",
    "responsible_layer",
]

#: Which layer owns a family, and the inputs that layer needs. A continuation is
#: state, not a task: the Astral Resonance Director arbitrates it from quota,
#: difficulty, wall clock, stalls and local capacity, and a prompt of nine
#: characters carries none of them. Handing a continuation to the signature path
#: would ask a predictor to invent an ask the person never typed, and would let
#: one layer silently take over the other's decision.
RESPONSIBILITY: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "continuation": (
        "director",
        ("quota", "difficulty", "time_budget", "stalls", "capacity"),
    ),
    "ask": ("parcimonia", ("signature", "capabilities", "verifier")),
}

#: Whole-text continuations, in the languages this store is written in. The list
#: is a starting point to be ratified, not a discovery: a term is only trusted
#: when the whole text is that term.
CONTINUATION_TERMS: frozenset[str] = frozenset(
    {
        "continuer",
        "continue",
        "continu",
        "continues",
        "ok",
        "oui",
        "non",
        "yes",
        "next",
        "suite",
        "suivant",
        "encore",
        "vas y",
        "vas-y",
        "poursuis",
        "poursuit",
        "on continue",
        "go",
    }
)

#: Words that carry no discriminating power for a hint proposal.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "ai", "au", "aux", "avec", "ce", "cela", "ces", "cet", "cette",
        "dans", "de", "des", "du", "elle", "en", "est", "et", "eu", "il", "ils",
        "je", "la", "le", "les", "leur", "lui", "ma", "mais", "me", "mes", "moi",
        "mon", "ne", "nos", "notre", "nous", "on", "ont", "ou", "par", "pas",
        "pour", "qu", "que", "quel", "quelle", "qui", "sa", "se", "ses", "son",
        "sont", "sur", "ta", "te", "tes", "toi", "ton", "tu", "un", "une", "va",
        "voir", "vos", "votre", "vous", "y",
        "a", "about", "all", "an", "and", "any", "are", "as", "at", "be", "by",
        "can", "do", "does", "for", "from", "get", "give", "has", "have", "how",
        "i", "if", "in", "is", "it", "its", "me", "my", "of", "on", "or", "our",
        "please", "so", "some", "that", "the", "their", "them", "then", "there",
        "these", "they", "this", "to", "us", "use", "want", "was", "we", "what",
        "when", "which", "who", "why", "will", "with", "you", "your",
        # Function words that carry no discriminating power in either language.
        "again", "already", "also", "always", "been", "being", "both", "but",
        "down", "each", "even", "ever", "here", "just", "less", "more", "never",
        "not", "now", "only", "other", "out", "over", "same", "still", "than",
        "too", "under", "up", "while", "yet",
        "ainsi", "aussi", "bien", "deja", "donc", "encore", "entre", "meme",
        "moins", "parce", "pendant", "plus", "seulement", "surtout", "tout",
        "tous", "toute", "tres",
    }
)

#: Connectives that often join two pieces of work in one input.
_CONNECTIVES: frozenset[str] = frozenset(
    {"aussi", "puis", "ensuite", "egalement", "and", "then", "also", "plus"}
)


def _normalise(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string.")
    # Collapse first, then remove the closing punctuation and the space it may
    # have left behind, so that "oui !" is the same whole text as "oui".
    return " ".join(text.strip().lower().split()).rstrip("!.?…").strip()


def _actions_in(tokens: Sequence[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for token in tokens:
        action = VERB_LEXICON.get(token)
        if action is not None and action not in seen:
            seen.append(action)
    return tuple(seen)


def classify_prompt(
    text: str, *, max_continuation_chars: int = 30
) -> tuple[str, str]:
    """Return a family and the rule that decided it.

    The strict rule trusts only a whole-text continuation term. The loose rule
    also accepts a short text that carries no action verb, which is right for a
    terse follow-up and wrong for a terse ask; the corpus reports both so the
    sensitivity is visible instead of being hidden behind one choice.
    """
    if type(max_continuation_chars) is not int or max_continuation_chars < 1:
        raise ValueError("max_continuation_chars must be a positive integer.")
    normalised = _normalise(text)
    if normalised in CONTINUATION_TERMS:
        return ("continuation", "whole_text_term")
    tokens = tokens_of(normalised)
    if len(normalised) <= max_continuation_chars and not _actions_in(tokens):
        return ("continuation", "short_without_action")
    return ("ask", "carries_an_action")


def _volume(entries: Sequence[Mapping[str, Any]]) -> int:
    return sum(int(entry.get("count", 1)) for entry in entries)


def partition_prompts(
    prompts: Sequence[Mapping[str, Any]], *, max_continuation_chars: int = 30
) -> dict[str, Any]:
    """Split a corpus into continuations and asks, strictly and loosely."""
    declared = [entry for entry in prompts if isinstance(entry, Mapping)]
    if not declared:
        raise ValueError("at least one prompt is required.")
    families: dict[str, list[Mapping[str, Any]]] = {
        "strict_continuation": [],
        "loose_continuation": [],
        "ask": [],
    }
    for entry in declared:
        family, rule = classify_prompt(
            str(entry.get("text", "")), max_continuation_chars=max_continuation_chars
        )
        if family == "continuation":
            families["loose_continuation"].append(entry)
            if rule == "whole_text_term":
                families["strict_continuation"].append(entry)
        else:
            families["ask"].append(entry)

    total_volume = _volume(declared)
    return {
        "distinct_prompts": len(declared),
        "total_volume": total_volume,
        "strict_continuation": {
            "distinct": len(families["strict_continuation"]),
            "volume": _volume(families["strict_continuation"]),
        },
        "loose_continuation": {
            "distinct": len(families["loose_continuation"]),
            "volume": _volume(families["loose_continuation"]),
        },
        "ask": {
            "distinct": len(families["ask"]),
            "volume": _volume(families["ask"]),
        },
        "ask_share_of_volume": round(_volume(families["ask"]) / total_volume, 4),
        "loose_share_of_volume": round(
            _volume(families["loose_continuation"]) / total_volume, 4
        ),
    }


def multi_ask_candidates(prompts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Count asks that look like they hold more than one piece of work.

    The count is an upper bound, not a detection: two connectives or two distinct
    actions in one text can also describe a single task. It bounds how much work a
    decomposition would even have to bite on, which is the question worth asking
    before building one.
    """
    declared = [entry for entry in prompts if isinstance(entry, Mapping)]
    if not declared:
        raise ValueError("at least one prompt is required.")
    single: list[Mapping[str, Any]] = []
    several: list[Mapping[str, Any]] = []
    for entry in declared:
        tokens = tokens_of(str(entry.get("text", "")))
        actions = _actions_in(tokens)
        connectives = sum(1 for token in tokens if token in _CONNECTIVES)
        if len(actions) >= 2 or connectives >= 2:
            several.append(entry)
        else:
            single.append(entry)
    total = _volume(declared)
    return {
        "distinct_prompts": len(declared),
        "several_work_candidates": {
            "distinct": len(several),
            "volume": _volume(several),
        },
        "single_work": {"distinct": len(single), "volume": _volume(single)},
        "several_share_of_volume": round(_volume(several) / total, 4),
        "reading": "an upper bound: two actions or two connectives may still be one task",
    }


def responsible_layer(family: str) -> tuple[str, tuple[str, ...]]:
    """Return the layer that owns a family and the inputs it needs.

    This is a boundary, not a router: it names who decides and with what, so that
    a caller cannot feed a continuation to the signature path without noticing.
    The decision itself stays with the layer that owns it.
    """
    if not isinstance(family, str) or family not in RESPONSIBILITY:
        raise ValueError(
            f"family must be one of {sorted(RESPONSIBILITY)}; a family nobody "
            "declared has no owner and no inputs."
        )
    return RESPONSIBILITY[family]


def propose_taxonomy(
    prompts: Sequence[Mapping[str, Any]],
    *,
    max_hints: int = 8,
    min_hint_count: int = 3,
) -> dict[str, Any]:
    """Propose candidate hints per action from the corpus, and say what it misses.

    Nothing here is a declaration: the caller ratifies the vocabulary, and the
    artefact must then be measured on prompts it was not derived from.

    A term earns its place by separating one action from the others, not by being
    frequent: a word common to every action describes none of them. The census is
    by token, so a plural is a separate row from its singular; the caller should
    ratify one form per concept.
    """
    if type(max_hints) is not int or max_hints < 1:
        raise ValueError("max_hints must be a positive integer.")
    if type(min_hint_count) is not int or min_hint_count < 1:
        raise ValueError("min_hint_count must be a positive integer.")
    declared = [entry for entry in prompts if isinstance(entry, Mapping)]
    if not declared:
        raise ValueError("at least one prompt is required.")

    by_action: dict[str, dict[str, int]] = {}
    overall: dict[str, int] = {}
    action_volume: dict[str, int] = {}
    unreached: list[Mapping[str, Any]] = []
    for entry in declared:
        tokens = tokens_of(str(entry.get("text", "")))
        actions = _actions_in(tokens)
        weight = int(entry.get("count", 1))
        if not actions:
            unreached.append(entry)
            continue
        for action in actions:
            action_volume[action] = action_volume.get(action, 0) + weight
            terms = by_action.setdefault(action, {})
            for token in set(tokens):
                if token in STOPWORDS or token in VERB_LEXICON:
                    continue
                if len(token) < 3:
                    continue
                terms[token] = terms.get(token, 0) + weight
                overall[token] = overall.get(token, 0) + weight

    total_volume = _volume(declared)
    proposals: dict[str, list[dict[str, Any]]] = {}
    for action, terms in sorted(by_action.items()):
        inside_total = max(1, action_volume.get(action, 1))
        outside_total = max(1, total_volume - action_volume.get(action, 0))
        scored: list[tuple[float, int, str]] = []
        for term, weight in terms.items():
            if weight < min_hint_count:
                continue
            # A hint earns its place by separating one action from the others, not
            # by being frequent: a word common to every action describes none.
            inside_share = weight / inside_total
            outside_share = (overall.get(term, weight) - weight) / outside_total
            discrimination = inside_share - outside_share
            if discrimination <= 0:
                continue
            scored.append((discrimination, weight, term))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        proposals[action] = [
            {
                "hint": term,
                "weight": weight,
                "discrimination": round(discrimination, 4),
            }
            for discrimination, weight, term in scored[:max_hints]
        ]
    total = _volume(declared)
    return {
        "distinct_prompts": len(declared),
        "total_volume": total,
        "action_volume": dict(sorted(action_volume.items())),
        "unreached": {
            "distinct": len(unreached),
            "volume": _volume(unreached),
            "share_of_volume": round(_volume(unreached) / total, 4),
        },
        "proposed_hints": proposals,
        "needs_ratification": True,
        "reading": (
            "candidate hints drawn from the corpus; the caller declares them, and "
            "they must be measured on prompts this proposal was not derived from"
        ),
    }
