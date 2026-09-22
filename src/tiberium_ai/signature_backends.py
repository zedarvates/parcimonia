"""Candidate producers of a task signature, behind the one reflex contract.

Two backends live here, and they answer the same questions in the same shape as
the keyword rule, so a caller swaps one for another without touching the
contract, the thresholds, the provenance or the calibration:

* a verb-frame backend reads the structure of the input: the head verb gives the
  action, the span after it gives the object, and the prepositional spans give
  the sources and the constraints. A declared hint only counts when it lands in a
  span that can carry it, which is what stops an accidental match such as the
  word before being read as a deadline.
* a KNN backend averages the recorded answers of the nearest labelled inputs. It
  retrieves rather than generalises, so its memory is the answer format itself
  and its blind spot is anything inedit.

Neither loads weights and neither touches the network. The verb lexicon is a
general list, not a list tuned to one corpus: when it helps, the help is
structural, and the paraphrase half of the corpus is the test that says so.

Known limits, stated because they are the honest cost of the approach: the frame
does not resolve passives or nominalisations, its lexicon speaks one action per
verb, and a KNN over sparse labels inherits their silence, because an unlabelled
dimension is read as no rather than as unknown.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .task_signature import (
    GOAL_QUESTION,
    KIND_QUESTION,
    NO_GOAL,
    SignatureCase,
    SignatureSchema,
)

__all__ = [
    "DELIMITERS",
    "INTERROGATIVE_MARKERS",
    "MIN_TOLERANT_LENGTH",
    "VERB_LEXICON",
    "KnnSignatureBackend",
    "LayeredSignatureBackend",
    "SignatureMemoryEntry",
    "VerbFrameSignatureBackend",
    "memory_from_cases",
    "normalise_text",
    "tokens_of",
    "verb_action",
]

#: Verbs mapped to the action they express. The action name is matched against a
#: declared kind by name, then by the kind's hints, so a caller keeps its own
#: vocabulary instead of adopting this one.
VERB_LEXICON: Mapping[str, str] = {
    "extract": "extract",
    "extracts": "extract",
    "extracted": "extract",
    "parse": "extract",
    "parses": "extract",
    "parsed": "extract",
    "pull": "extract",
    "pulls": "extract",
    "get": "extract",
    "gets": "extract",
    "read": "extract",
    "reads": "extract",
    "retrieve": "extract",
    "fetch": "extract",
    "list": "extract",
    "dump": "extract",
    "format": "format",
    "formats": "format",
    "reformat": "format",
    "tidy": "format",
    "clean": "format",
    "rewrite": "format",
    "normalise": "format",
    "normalize": "format",
    "make": "format",
    "render": "format",
    "summarise": "summarise",
    "summarize": "summarise",
    "choose": "decide",
    "select": "decide",
    "pick": "decide",
    "decide": "decide",
    "rank": "decide",
    "prioritise": "decide",
    "prioritize": "decide",
    "verify": "verify",
    "validate": "verify",
    "check": "verify",
    "test": "verify",
    "confirm": "verify",
    "audit": "verify",
    "ensure": "verify",
    "extraire": "extract",
    "extrais": "extract",
    "extrait": "extract",
    "parser": "extract",
    "recuperer": "extract",
    "recupere": "extract",
    "recuperes": "extract",
    "lire": "extract",
    "lis": "extract",
    "prendre": "extract",
    "prends": "extract",
    "donne": "extract",
    "donner": "extract",
    "sors": "extract",
    "sortir": "extract",
    "affiche": "extract",
    "afficher": "extract",
    "montre": "extract",
    "montrer": "extract",
    "lister": "extract",
    "liste": "extract",
    "formater": "format",
    "formate": "format",
    "reformater": "format",
    "reecrire": "format",
    "reecris": "format",
    "mettre": "format",
    "mets": "format",
    "rendre": "format",
    "rends": "format",
    "corriger": "format",
    "simplifier": "format",
    "resumer": "format",
    "choisir": "decide",
    "choisis": "decide",
    "selectionner": "decide",
    "selectionne": "decide",
    "trancher": "decide",
    "tranche": "decide",
    "verifier": "verify",
    "verifie": "verify",
    "valider": "verify",
    "valide": "verify",
    "controler": "verify",
    "controle": "verify",
    "tester": "verify",
    "teste": "verify",
    "auditer": "verify",
    "confirmer": "verify",
    "confirme": "verify",
    # Categories of well-formed public instructions, added from the category
    # names and from general usage, never from an instruction of the corpus.
    "condense": "summarise",
    "shorten": "summarise",
    "abridge": "summarise",
    "recap": "summarise",
    "classify": "classify",
    "categorise": "classify",
    "categorize": "classify",
    "label": "classify",
    "sort": "classify",
    "group": "classify",
    "tag": "classify",
    "write": "generate",
    "generate": "generate",
    "create": "generate",
    "draft": "generate",
    "compose": "generate",
    "produce": "generate",
    "invent": "generate",
    "brainstorm": "propose",
    "propose": "propose",
    "suggest": "propose",
    "answer": "answer",
    "explain": "answer",
    "describe": "answer",
    "tell": "answer",
    "state": "answer",
    "define": "answer",
    "translate": "answer",
    "compare": "answer",
    "calculate": "answer",
    "compute": "answer",
    "solve": "answer",
    # Declared from the category semantics and from general usage, after a census
    # showed which imperatives a real corpus uses and the lexicon did not know.
    # "continuer" is deliberately absent: a bare continuation belongs to the
    # director, and inventing an action for it would invent an ask.
    "faire": "generate",
    "fais": "generate",
    "faites": "generate",
    "creer": "generate",
    "cree": "generate",
    "crees": "generate",
    "generer": "generate",
    "genere": "generate",
    "ameliorer": "generate",
    "ameliore": "generate",
    "developper": "generate",
    "developpe": "generate",
    # An observed misspelling, declared on purpose: it appears ten times in real
    # data and it is two edits from the canonical form, so tolerance would not
    # catch it and guessing at that distance would be worse than declaring.
    "develloper": "generate",
    "devellope": "generate",
    "ajouter": "generate",
    "ajoute": "generate",
    "commencer": "generate",
    "commence": "generate",
    "finir": "generate",
    "finis": "generate",
    "finie": "generate",
    "jouer": "generate",
    "joue": "generate",
    "optimiser": "generate",
    "optimise": "generate",
    "automatiser": "generate",
    "automatise": "generate",
    "refactorer": "generate",
    "refactoriser": "generate",
    "migrer": "generate",
    "migre": "generate",
    "installer": "generate",
    "installe": "generate",
    "documenter": "generate",
    "documente": "generate",
    "traduire": "generate",
    "traduis": "generate",
    "publier": "generate",
    "publie": "generate",
    "envoyer": "generate",
    "envoie": "generate",
    "lancer": "generate",
    "lance": "generate",
    "connecter": "generate",
    "brancher": "generate",
    "decouper": "generate",
    "renommer": "generate",
    "deployer": "generate",
    "build": "generate",
    "add": "generate",
    "fix": "generate",
    "implement": "generate",
    "improve": "generate",
    "extend": "generate",
    "update": "generate",
    "split": "generate",
    "move": "generate",
    "rename": "generate",
    "refactor": "generate",
    "migrate": "generate",
    "install": "generate",
    "optimise": "generate",
    "optimize": "generate",
    "document": "generate",
    "translate": "generate",
    "publish": "generate",
    "send": "generate",
    "launch": "generate",
    "deploy": "generate",
    "wire": "generate",
    "reorganiser": "format",
    "reorganise": "format",
    "nettoyer": "format",
    "diagnostiquer": "verify",
    "deboguer": "verify",
    "inspecter": "verify",
    "review": "verify",
    "inspect": "verify",
    "debug": "verify",
    "chercher": "extract",
    "trouver": "extract",
    "compter": "extract",
    "mesurer": "extract",
    "search": "extract",
    "find": "extract",
    "count": "extract",
    "measure": "extract",
    "arbitrer": "decide",
    "prioriser": "decide",
    "classer": "classify",
    "trier": "classify",
    "ranger": "classify",
    "proposer": "propose",
    "suggerer": "propose",
    "repondre": "answer",
    "expliquer": "answer",
    "decrire": "answer",
    "compare": "answer",
    "prioritize": "decide",
}

#: Lexicon keys grouped by length, so a tolerant lookup can skip everything that
#: cannot possibly be one edit away.
_KEYS_BY_LENGTH: dict[int, tuple[str, ...]] = {}
for _key in sorted(VERB_LEXICON):
    _KEYS_BY_LENGTH.setdefault(len(_key), ())
    _KEYS_BY_LENGTH[len(_key)] = _KEYS_BY_LENGTH[len(_key)] + (_key,)

#: Below this length a single edit is a fifth of the word and the match stops
#: being evidence: "rendu" is one substitution from the imperative "rends", and
#: that false positive is what raised this floor.
MIN_TOLERANT_LENGTH = 6


def _within_one_edit(left: str, right: str) -> bool:
    """Return whether two tokens differ by at most one edit.

    One insertion, deletion or substitution counts, and so does an adjacent
    transposition: that is the shape a hurried typist produces, and it is exactly
    the typo found in a real corpus, which plain Levenshtein would score as two
    substitutions and miss.
    """
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differing = [index for index in range(len(left)) if left[index] != right[index]]
        if len(differing) == 2 and differing[1] == differing[0] + 1:
            first = differing[0]
            return left[first] == right[first + 1] and left[first + 1] == right[first]
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    index = 0
    offset = 0
    skipped = False
    while index < len(shorter) and offset < len(longer):
        if shorter[index] == longer[offset]:
            index += 1
            offset += 1
            continue
        if skipped:
            return False
        skipped = True
        if len(shorter) == len(longer):
            index += 1
        offset += 1
    return True


def verb_action(token: str, *, tolerant: bool = True) -> tuple[str, bool] | None:
    """Return the action a token names, and whether the match was exact.

    Tolerance is tried only against keys of a neighbouring length, and never
    below the declared minimum, so a short token is refused instead of being
    stretched into a verb it does not look like.
    """
    if not isinstance(token, str):
        raise TypeError("token must be a string.")
    exact = VERB_LEXICON.get(token)
    if exact is not None:
        return (exact, True)
    if not tolerant or len(token) < MIN_TOLERANT_LENGTH:
        return None
    for length in (len(token), len(token) - 1, len(token) + 1):
        for key in _KEYS_BY_LENGTH.get(length, ()):
            if _within_one_edit(token, key):
                return (VERB_LEXICON[key], False)
    return None

#: Tokens that end a span. A hint found after one of these belongs to an adjunct
#: rather than to the object, and every declaration is weighted accordingly.
DELIMITERS: frozenset[str] = frozenset(
    {
        "a", "about", "after", "and", "as", "at", "au", "aux", "avant", "avec",
        "before", "by", "dans", "de", "depuis", "des", "du", "en", "et", "for",
        "from", "in", "into", "of", "on", "par", "pour", "puis", "que", "qui",
        "sur", "that", "then", "to", "using", "vers", "via", "when", "which",
        "with",
    }
)

_WORD_PATTERN = re.compile(r"[a-z0-9]+")

#: Words that open a question. A question has no head verb to read, which is why
#: a verb-driven frame abstains on it; these markers are the fallback that names
#: the ask as one for an answer. Auxiliaries are included on purpose: they are
#: not in the verb lexicon, so they can only fire when no verb was found.
INTERROGATIVE_MARKERS: frozenset[str] = frozenset(
    {
        "what", "why", "how", "when", "where", "who", "whom", "whose", "which",
        "is", "are", "was", "were", "does", "do", "did", "can", "could", "should",
        "would", "will", "has", "have", "may", "might",
        "quel", "quelle", "quels", "quelles", "comment", "pourquoi", "combien",
        "qui", "que", "quoi", "ou", "est", "sont", "peut", "peux", "pourrait",
    }
)


def normalise_text(text: str) -> str:
    """Lowercase, strip accents and keep alphanumeric runs as single tokens."""
    if not isinstance(text, str):
        raise TypeError("text must be a string.")
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(_WORD_PATTERN.findall(stripped))


def tokens_of(text: str) -> tuple[str, ...]:
    """Return the normalised tokens of one input."""
    return tuple(normalise_text(text).split())


def _span_text(tokens: Sequence[str], start: int, end: int) -> str:
    return " ".join(tokens[start:end])


def _weight(
    hints: Sequence[str],
    object_text: str,
    adjuncts: Sequence[str],
    *,
    adjunct_weight: float = 0.8,
) -> float:
    """Weight a declaration by the span its hint lands in.

    A hint that appears only outside every span is worth nothing: the subject and
    the leftovers of a request are not where a deliverable or a constraint lives.
    """
    for hint in hints:
        needle = normalise_text(hint)
        if not needle:
            continue
        if needle in object_text:
            return 1.0
        for adjunct in adjuncts:
            if needle in adjunct:
                return adjunct_weight
    return 0.0


def _uniform(keys: Sequence[str]) -> dict[str, float]:
    weight = 1.0 / len(keys)
    return {key: weight for key in keys}


def _no_answer(question: Any) -> Mapping[str, Any]:
    """Answer a question the backend knows nothing about, without inventing."""
    if question.kind.value == "choice":
        keys = list(question.option_keys)
        return {"choice": keys[0], "probabilities": _uniform(keys), "confidence": None}
    return {
        "noul": 0.0,
        "probabilities": {"false": 1.0, "true": 0.0},
        "confidence": None,
    }


def _noul(probability: float) -> Mapping[str, Any]:
    return {
        "noul": probability,
        "probabilities": {"false": 1.0 - probability, "true": probability},
        "confidence": None,
    }


def _certainty(question: Any, answer: object) -> float | None:
    """Return how far an answer is from a coin flip, or null when it is unusable.

    A confident no is as informative as a confident yes, so a boolean answer is
    measured by its distance from one half rather than by its probability of yes.
    """
    if not isinstance(answer, Mapping):
        return None
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, Mapping):
        return None
    if question.kind.value == "choice":
        chosen = answer.get("choice")
        if chosen is None:
            return None
        value = probabilities.get(chosen)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return float(value)
    true_probability = probabilities.get("true")
    if not isinstance(true_probability, (int, float)) or isinstance(
        true_probability, bool
    ):
        return None
    return max(float(true_probability), 1.0 - float(true_probability))


@dataclass(frozen=True)
class LayeredSignatureBackend:
    """Take the primary where it is certain, the fallback everywhere else.

    The candidates are not substitutes. On public instructions the retrieval
    backend is the accurate one on about a third of the cases, and the lexical
    rule is the one that answers at all; layering them is how a route gets the
    coverage of one and the precision of the other.

    The choice is per question rather than per input, because two mechanisms do
    not know the same things: a retrieved neighbour can settle a field while
    remaining unsure of the act, and the fallback should then decide the act
    alone.
    """

    primary: Any
    fallback: Any
    primary_floor: float = 0.9
    latin_only: bool = False

    def __post_init__(self) -> None:
        for name in ("primary", "fallback"):
            if not callable(getattr(getattr(self, name), "evaluate", None)):
                raise TypeError(
                    f"{name} must provide an evaluate(state, questions) method."
                )
        if not 0.0 <= self.primary_floor <= 1.0:
            raise ValueError("primary_floor must be a number in [0, 1].")
        if type(self.latin_only) is not bool:
            raise TypeError("latin_only must be a boolean.")

    def evaluate(
        self, state_text: str, questions: Sequence[Any]
    ) -> Mapping[str, Mapping[str, Any]]:
        primary = self.primary.evaluate(state_text, questions)
        fallback = self.fallback.evaluate(state_text, questions)
        answers: dict[str, Mapping[str, Any]] = {}
        for question in questions:
            candidate = primary.get(question.name)
            certainty = _certainty(question, candidate)
            if certainty is not None and certainty >= self.primary_floor:
                answers[question.name] = dict(candidate)
                continue
            alternative = fallback.get(question.name)
            answers[question.name] = (
                _no_answer(question) if alternative is None else dict(alternative)
            )
        return answers


def _specific_kind(
    schema: SignatureSchema, text: str
) -> tuple[str | None, bool]:
    """Return the most specific declared kind the text points at, and whether it tied.

    A hint that is itself an interrogative marker carries no specificity, so it
    is excluded: otherwise the generic question word would win every comparison
    against the very hints that say what the ask actually wants. The longest
    matching hint wins, because longer usually means less generic, and a tie
    abstains instead of picking one of two readings.
    """
    scored: list[tuple[int, str]] = []
    for item in schema.kinds:
        lengths = [
            len(needle)
            for hint in item.hints
            for needle in (normalise_text(hint),)
            if needle and needle not in INTERROGATIVE_MARKERS and needle in text
        ]
        if lengths:
            scored.append((max(lengths), item.name))
    if not scored:
        return (None, False)
    best = max(length for length, _ in scored)
    winners = sorted(name for length, name in scored if length == best)
    if len(winners) != 1:
        return (None, True)
    return (winners[0], False)


def _declarations(
    schema: SignatureSchema,
    tokens: Sequence[str],
    *,
    interrogative: bool = True,
    specificity: bool = True,
) -> dict[str, Any]:
    """Read the frame: head verb, object span, then the adjunct spans."""
    verb_index: int | None = None
    action: str | None = None
    for index, token in enumerate(tokens):
        candidate = VERB_LEXICON.get(token)
        if candidate is not None:
            verb_index, action = index, candidate
            break
    if verb_index is None:
        # Tolerance is a last resort: an exact verb anywhere in the text wins, so
        # a typo can never outrank a word the lexicon actually knows.
        for index, token in enumerate(tokens):
            found = verb_action(token)
            if found is not None:
                verb_index, action = index, found[0]
                break
    empty: dict[str, Any] = {
        "action": None,
        "object": "",
        "adjuncts": (),
        "fields": {},
        "capabilities": {},
        "goals": {},
    }
    if verb_index is None or action is None:
        if interrogative and tokens and tokens[0] in INTERROGATIVE_MARKERS:
            if specificity:
                specific, ambiguous = _specific_kind(schema, " ".join(tokens))
                if ambiguous:
                    return empty
                if specific is not None:
                    return {**empty, "action": specific, "interrogative": True}
            # No head verb and nothing specific: the ask is a question, and a
            # question wants an answer.
            return {**empty, "action": "answer", "interrogative": True}
        return empty

    start = verb_index + 1
    object_end = len(tokens)
    for index in range(start, len(tokens)):
        if tokens[index] in DELIMITERS:
            object_end = index
            break
    adjuncts: list[str] = []
    cursor = object_end
    while cursor < len(tokens):
        if tokens[cursor] in DELIMITERS:
            cursor += 1
            continue
        end = cursor
        while end < len(tokens) and tokens[end] not in DELIMITERS:
            end += 1
        adjuncts.append(_span_text(tokens, cursor, end))
        cursor = end

    object_text = _span_text(tokens, start, object_end)
    return {
        "action": action,
        "interrogative": False,
        "object": object_text,
        "adjuncts": tuple(adjuncts),
        "fields": {
            item.name: _weight(item.hints, object_text, adjuncts)
            for item in schema.fields
        },
        "capabilities": {
            item.name: _weight(item.hints, object_text, adjuncts)
            for item in schema.capabilities
        },
        "goals": {
            item.name: _weight(item.hints, object_text, adjuncts, adjunct_weight=1.0)
            for item in schema.goals
        },
    }


@dataclass(frozen=True)
class VerbFrameSignatureBackend:
    """Read the action from the head verb and the rest from span position."""

    schema: SignatureSchema
    #: Read a question with no head verb as an ask for an answer. Switching it
    #: off is the control arm of the experiment, not a configuration to hide.
    interrogative_signal: bool = True
    #: Let a longer, non-interrogative hint beat the generic question marker.
    #: Measured on two unread public slices and switched off: it earned nothing
    #: on the classes it was written for, because the hints it keys on almost
    #: never appear there, and its point estimate on agreement was negative. The
    #: arm stays available so the experiment remains reproducible.
    specificity_tie_break: bool = False
    latin_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.schema, SignatureSchema):
            raise TypeError("schema must be a SignatureSchema instance.")
        if type(self.interrogative_signal) is not bool:
            raise TypeError("interrogative_signal must be a boolean.")
        if type(self.specificity_tie_break) is not bool:
            raise TypeError("specificity_tie_break must be a boolean.")
        if type(self.latin_only) is not bool:
            raise TypeError("latin_only must be a boolean.")

    def evaluate(
        self, state_text: str, questions: Sequence[Any]
    ) -> Mapping[str, Mapping[str, Any]]:
        selected = _declarations(
            self.schema,
            tokens_of(state_text),
            interrogative=self.interrogative_signal,
            specificity=self.specificity_tie_break,
        )
        action = selected["action"]
        answers: dict[str, Mapping[str, Any]] = {}
        for question in questions:
            if question.name == KIND_QUESTION:
                answers[question.name] = self._kind_answer(question, action)
            elif question.name == GOAL_QUESTION:
                answers[question.name] = self._goal_answer(question, selected["goals"])
            elif question.name.startswith("field."):
                name = question.name[len("field.") :]
                answers[question.name] = _noul(selected["fields"].get(name, 0.0))
            elif question.name.startswith("capability."):
                name = question.name[len("capability.") :]
                answers[question.name] = _noul(selected["capabilities"].get(name, 0.0))
            else:
                answers[question.name] = _no_answer(question)
        return answers

    def _kind_answer(self, question: Any, action: str | None) -> Mapping[str, Any]:
        keys = list(question.option_keys)
        matched = self._kind_for_action(action) if action else None
        if matched is None or matched not in keys:
            # No frame, or an action the caller never declared: a uniform answer
            # is the honest unknown and the threshold turns it into an abstention.
            return {
                "choice": keys[0],
                "probabilities": _uniform(keys),
                "confidence": None,
            }
        return {
            "choice": matched,
            "probabilities": {key: (1.0 if key == matched else 0.0) for key in keys},
            "confidence": None,
        }

    def _kind_for_action(self, action: str) -> str | None:
        for item in self.schema.kinds:
            if item.name == action:
                return item.name
            if any(normalise_text(hint) == action for hint in item.hints):
                return item.name
        return None

    def _goal_answer(
        self, question: Any, scores: Mapping[str, float]
    ) -> Mapping[str, Any]:
        keys = list(question.option_keys)
        best = max(scores.items(), key=lambda pair: pair[1]) if scores else None
        if best is None or best[1] < 1.0:
            return {
                "choice": NO_GOAL,
                "probabilities": {
                    key: (1.0 if key == NO_GOAL else 0.0) for key in keys
                },
                "confidence": None,
            }
        return {
            "choice": best[0],
            "probabilities": {key: (1.0 if key == best[0] else 0.0) for key in keys},
            "confidence": None,
        }


@dataclass(frozen=True)
class SignatureMemoryEntry:
    """One labelled input and the answers it should produce."""

    case_id: str
    prompt: str
    answers: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("case_id must be a nonempty, trimmed string.")
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be a nonempty string.")
        if not isinstance(self.answers, Mapping) or not self.answers:
            raise ValueError("answers must be a non-empty mapping.")


def memory_from_cases(
    cases: Sequence[SignatureCase], schema: SignatureSchema
) -> tuple[SignatureMemoryEntry, ...]:
    """Turn labelled cases into the answer memory a retrieval backend reads.

    Only what the labels state is written. A dimension a label does not mention
    is written as false rather than as unknown, which is the known silence of a
    sparse label set and not the same thing as a negative observation.
    """
    if not isinstance(schema, SignatureSchema):
        raise TypeError("schema must be a SignatureSchema instance.")
    kind_keys = [item.name for item in schema.kinds]
    goal_keys = schema.goal_names() if schema.goals else []
    entries: list[SignatureMemoryEntry] = []
    for case in cases:
        if not isinstance(case, SignatureCase):
            raise TypeError("cases must contain SignatureCase instances.")
        if case.kind not in kind_keys:
            raise ValueError(f"case {case.case_id!r} names an undeclared kind.")
        answers: dict[str, Mapping[str, Any]] = {
            KIND_QUESTION: {
                "choice": case.kind,
                "probabilities": {
                    key: (1.0 if key == case.kind else 0.0) for key in kind_keys
                },
                "confidence": None,
            }
        }
        for name in schema.field_names():
            answers[f"field.{name}"] = _noul(1.0 if name in case.fields else 0.0)
        for name in schema.capability_names():
            answers[f"capability.{name}"] = _noul(0.0)
        if goal_keys:
            chosen = case.goal if case.goal in goal_keys else NO_GOAL
            answers[GOAL_QUESTION] = {
                "choice": chosen,
                "probabilities": {
                    key: (1.0 if key == chosen else 0.0) for key in goal_keys
                },
                "confidence": None,
            }
        entries.append(
            SignatureMemoryEntry(
                case_id=case.case_id, prompt=case.prompt, answers=answers
            )
        )
    return tuple(entries)


@dataclass(frozen=True)
class KnnSignatureBackend:
    """Average the recorded answers of the nearest labelled inputs.

    Similarity is a token Jaccard, so the backend stays deterministic and needs
    no weights. A neighbour below the similarity floor is not a neighbour: with
    none left, the answer is the honest unknown rather than the closest guess.
    """

    memory: tuple[SignatureMemoryEntry, ...]
    k: int = 3
    min_similarity: float = 0.2
    latin_only: bool = False

    def __post_init__(self) -> None:
        if type(self.k) is not int or self.k < 1:
            raise ValueError("k must be a positive integer.")
        if not 0.0 <= self.min_similarity <= 1.0:
            raise ValueError("min_similarity must be a number in [0, 1].")
        if not all(isinstance(entry, SignatureMemoryEntry) for entry in self.memory):
            raise TypeError("memory must contain SignatureMemoryEntry instances.")

    def neighbours(
        self, state_text: str
    ) -> tuple[tuple[float, SignatureMemoryEntry], ...]:
        """Return the nearest memories above the floor, strongest first."""
        wanted = set(tokens_of(state_text))
        if not wanted:
            return ()
        scored: list[tuple[float, SignatureMemoryEntry]] = []
        for entry in self.memory:
            candidate = set(tokens_of(entry.prompt))
            union = wanted | candidate
            if not union:
                continue
            similarity = len(wanted & candidate) / len(union)
            if similarity >= self.min_similarity:
                scored.append((similarity, entry))
        scored.sort(key=lambda pair: (-pair[0], pair[1].case_id))
        return tuple(scored[: self.k])

    def evaluate(
        self, state_text: str, questions: Sequence[Any]
    ) -> Mapping[str, Mapping[str, Any]]:
        neighbours = self.neighbours(state_text)
        if not neighbours:
            return {question.name: _no_answer(question) for question in questions}
        return {
            question.name: self._average(question, neighbours)
            for question in questions
        }

    def _average(
        self,
        question: Any,
        neighbours: Sequence[tuple[float, SignatureMemoryEntry]],
    ) -> Mapping[str, Any]:
        keys = list(question.option_keys)
        total = 0.0
        accumulator = {key: 0.0 for key in keys}
        for weight, entry in neighbours:
            answer = entry.answers.get(question.name)
            if not isinstance(answer, Mapping):
                continue
            probabilities = answer.get("probabilities")
            if not isinstance(probabilities, Mapping):
                continue
            total += weight
            for key in keys:
                value = probabilities.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    accumulator[key] += weight * float(value)
        if total <= 0.0:
            return _no_answer(question)
        averaged = {key: accumulator[key] / total for key in keys}
        if question.kind.value != "choice":
            return _noul(averaged.get("true", 0.0))
        share = sum(averaged.values())
        if share <= 0.0:
            return _no_answer(question)
        normalised = {key: averaged[key] / share for key in keys}
        chosen = max(keys, key=lambda key: (normalised[key], -keys.index(key)))
        return {
            "choice": chosen,
            "probabilities": normalised,
            "confidence": None,
        }
