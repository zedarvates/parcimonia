"""The public lane: well-formed instructions whose labels we did not write.

An authored corpus cannot settle a disagreement about its own labels, and a
measured bench where the same hand wrote the hints and the cases is a
self-consistency check. A public instruction set supplies what neither can: asks
written by strangers, and categories attributed by people who are not us.

Two honesty rules shape this module.

* the mapping from a public category to a declared kind is ours, so it is
  declared here in one readable table instead of being buried in a prompt. The
  labels are external; the mapping is not.
* a public corpus is not this system's work, so it measures a mechanism and can
  never authorize anything. Its cases carry situations_origin public and labels
  that are authored, which is what keeps the authorization gate shut.

Recommended protocol, because it is easy to break: extend the verb lexicon from
the category names and from general usage, freeze it, then fetch and measure
once. Reading instructions before freezing the lexicon turns the lane back into
a self-confirmation.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .task_signature import DeclaredItem, SignatureCase, SignatureSchema

__all__ = [
    "CATEGORY_TO_KIND",
    "PUBLIC_FIELD",
    "PUBLIC_KIND_HINTS",
    "PUBLIC_ORIGIN",
    "cases_from_rows",
    "public_schema",
    "public_split",
]

PUBLIC_ORIGIN = "public"

#: The one field a public instruction lets us label objectively: whether the ask
#: depends on a text supplied alongside it. The dataset states it, so the label
#: is not an opinion.
PUBLIC_FIELD = "attached_context"

#: Declared kinds and the vocabulary that may reach them.
PUBLIC_KIND_HINTS: Mapping[str, tuple[str, ...]] = {
    "extract": ("extract", "pull", "get", "find", "list", "retrieve"),
    "summarise": ("summarise", "summarize", "condense", "shorten", "recap", "summary"),
    "classify": ("classify", "categorize", "categorise", "label", "sort", "group", "tag"),
    "generate": ("write", "generate", "create", "draft", "compose", "produce", "invent"),
    "propose": ("brainstorm", "propose", "suggest", "idea", "come up with"),
    "answer": (
        "answer", "explain", "describe", "tell", "define", "translate", "compare",
        "calculate", "compute", "solve", "what", "why", "how", "when", "who",
    ),
}

#: Public category to declared kind. Closed qa, open qa and general qa are all
#: asks for an answer, so three categories reach one kind; nothing else merges.
CATEGORY_TO_KIND: Mapping[str, str] = {
    "information_extraction": "extract",
    "summarization": "summarise",
    "classification": "classify",
    "creative_writing": "generate",
    "brainstorming": "propose",
    "closed_qa": "answer",
    "open_qa": "answer",
    "general_qa": "answer",
}


def public_schema() -> SignatureSchema:
    """Return the declared sets this lane predicts within."""
    return SignatureSchema(
        name="public-instructions",
        kinds=tuple(
            DeclaredItem(name, hints) for name, hints in PUBLIC_KIND_HINTS.items()
        ),
        fields=(
            DeclaredItem(
                PUBLIC_FIELD,
                ("context", "following", "passage", "below", "above", "provided"),
            ),
        ),
    )


def cases_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    schema: SignatureSchema | None = None,
    id_prefix: str = "public",
) -> tuple[SignatureCase, ...]:
    """Turn fetched rows into cases, refusing a category nobody declared.

    A public corpus that grows a category is a signal to declare it on purpose,
    not a reason to guess one.
    """
    active = schema or public_schema()
    if not isinstance(id_prefix, str) or not id_prefix.strip():
        raise ValueError("id_prefix must be a nonempty string.")
    cases: list[SignatureCase] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError("rows must be mappings.")
        category = str(row.get("category", ""))
        if category not in CATEGORY_TO_KIND:
            raise ValueError(
                f"row {index} carries the undeclared category {category!r}; "
                "declare it in CATEGORY_TO_KIND on purpose."
            )
        instruction = str(row.get("instruction", "") or "")
        if not instruction.strip():
            raise ValueError(f"row {index} carries no instruction.")
        cases.append(
            SignatureCase(
                case_id=f"{id_prefix}-{index:04d}",
                prompt=instruction,
                kind=CATEGORY_TO_KIND[category],
                fields=(PUBLIC_FIELD,) if row.get("context_present") else (),
                situations_origin=PUBLIC_ORIGIN,
                label_origin="authored",
            )
        )
    return tuple(cases)


def public_split(
    cases: Sequence[SignatureCase], *, memory: int = 100
) -> tuple[tuple[SignatureCase, ...], tuple[SignatureCase, ...]]:
    """Split by position into a labelled memory and a disjoint evaluation set.

    A retrieval backend needs labelled examples to retrieve; giving it its own
    evaluation set would measure memorisation. The split is by declared order so
    it stays reproducible.
    """
    declared = tuple(cases)
    if type(memory) is not int or memory < 1:
        raise ValueError("memory must be a positive integer.")
    if memory >= len(declared):
        raise ValueError("the memory must leave at least one case to evaluate.")
    return declared[:memory], declared[memory:]
