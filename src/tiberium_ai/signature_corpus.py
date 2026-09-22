"""An authored signature corpus, split so the rule's brittleness is visible.

Everything here is authored: the situations were written for the test and the
labels were written by the same hand. The corpus therefore measures what the
rules do, never what a real task needed, and it can authorize nothing. Its
purpose is to produce the number a learner has to beat, and to keep that number
honest by not averaging two very different populations into one score.

The split matters more than the size:

* the aligned half writes its prompts with the declared hint vocabulary, which
  is the situation the rules were designed for
* the paraphrase half expresses the same intents with other words, including
  French, which is the situation a real input arrives in

Reporting one number over both halves would flatter the rule. Reporting them
apart says what is actually true: a keyword rule recognises its own vocabulary
and little else, and that gap is exactly what a KNN or a micro-NN is supposed to
close on labelled outcomes.

The schema below is an example vocabulary, not this project's official one. The
hints are the lever a caller tunes against real prompts.
"""

from __future__ import annotations

from .task_signature import DeclaredItem, SignatureCase, SignatureSchema

__all__ = [
    "aligned_cases",
    "all_cases",
    "example_schema",
    "paraphrase_cases",
]

AUTHORED = "authored"


def example_schema() -> SignatureSchema:
    """Return the example closed sets and their hint vocabulary."""
    return SignatureSchema(
        name="parcimonia-example",
        kinds=(
            DeclaredItem("extract", ("extract", "parse", "pull")),
            DeclaredItem("format", ("format", "tidy", "reformat")),
            DeclaredItem("decide", ("choose", "select", "pick")),
            DeclaredItem("verify", ("verify", "validate", "check")),
        ),
        capabilities=(
            DeclaredItem("route.knn", ("similar case", "precedent", "knn")),
            DeclaredItem("route.browser", ("browser", "web page", "screenshot")),
            DeclaredItem("route.local_model", ("local model", "offline model", "on device")),
            DeclaredItem("tool.shell", ("shell command", "command line", "script")),
        ),
        fields=(
            DeclaredItem("path", ("file", "path", "directory")),
            DeclaredItem("schema", ("schema", "fields", "columns")),
            DeclaredItem("deadline", ("deadline", "due by", "before")),
            DeclaredItem("budget", ("budget", "cost ceiling", "token limit")),
            DeclaredItem("language", ("language", "locale", "voice")),
        ),
        goals=(
            DeclaredItem("GOAL-PARCIMONIA", ("parcimonia", "cheapest mechanism", "routing cost")),
            DeclaredItem("GOAL-DOCS", ("documentation", "readme", "docs")),
        ),
    )


def aligned_cases() -> tuple[SignatureCase, ...]:
    """Cases written in the hint vocabulary, one intent each."""
    rows = (
        ("extract", "extract the schema of the file at this path", ("path", "schema"), None),
        ("extract", "parse the file and pull the columns", ("path", "schema"), None),
        ("extract", "pull the fields from the file", ("path", "schema"), None),
        ("extract", "extract the budget from the token limit line", ("budget",), None),
        ("format", "format this table and tidy it", (), None),
        ("format", "reformat the output", (), None),
        ("format", "reformat the language locale field", ("language",), None),
        ("decide", "choose the cheapest mechanism for this task", (), "GOAL-PARCIMONIA"),
        ("decide", "select the routing cost option", (), "GOAL-PARCIMONIA"),
        ("verify", "verify the schema against the file", ("path", "schema"), None),
        ("verify", "validate the columns of the file", ("path", "schema"), None),
        ("verify", "check the deadline before release", ("deadline",), None),
    )
    return tuple(
        SignatureCase(
            case_id=f"aligned-{index:02d}",
            prompt=prompt,
            kind=kind,
            fields=fields,
            goal=goal,
            situations_origin=AUTHORED,
            label_origin=AUTHORED,
        )
        for index, (kind, prompt, fields, goal) in enumerate(rows)
    )


def paraphrase_cases() -> tuple[SignatureCase, ...]:
    """The same intents in other words, which is how a real input arrives."""
    rows = (
        ("extract", "sors-moi les colonnes de ce CSV", ("schema",), None),
        ("extract", "récupère les champs de ce fichier", ("path", "schema"), None),
        ("extract", "get the column names out of this dump", ("schema",), None),
        ("format", "mets ce tableau au propre", (), None),
        ("format", "make this readable", (), None),
        ("decide", "quel mécanisme moins cher pour cette tâche ?", (), "GOAL-PARCIMONIA"),
        ("decide", "which of these two should I use", (), None),
        ("verify", "est-ce que ce résultat tient la route ?", (), None),
        ("verify", "contrôle la cohérence du rapport", (), None),
        ("format", "check the spelling of this sentence", (), None),
        ("decide", "reformat the options before deciding", (), None),
        ("verify", "tidy the report then confirm it", (), None),
    )
    return tuple(
        SignatureCase(
            case_id=f"paraphrase-{index:02d}",
            prompt=prompt,
            kind=kind,
            fields=fields,
            goal=goal,
            situations_origin=AUTHORED,
            label_origin=AUTHORED,
        )
        for index, (kind, prompt, fields, goal) in enumerate(rows)
    )


def all_cases() -> tuple[SignatureCase, ...]:
    """Return both halves, aligned first, for a caller that wants one run."""
    return aligned_cases() + paraphrase_cases()
