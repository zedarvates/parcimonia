import pytest

from tiberium_ai.real_asks import (
    looks_like_a_verb,
    reachable_schema,
    unreached_verb_candidates,
)
from tiberium_ai.signature_backends import VerbFrameSignatureBackend


class Silent:
    """A mechanism that never answers, so every ask counts as unreached."""

    latin_only = False

    def evaluate(self, state_text, questions):
        answers = {}
        for question in questions:
            keys = list(question.option_keys)
            if question.kind.value == "choice":
                weight = 1.0 / len(keys)
                answers[question.name] = {
                    "choice": keys[0],
                    "probabilities": {key: weight for key in keys},
                    "confidence": None,
                }
            else:
                answers[question.name] = {
                    "noul": 0.0,
                    "probabilities": {"false": 1.0, "true": 0.0},
                    "confidence": None,
                }
        return answers


def entry(text, count=1):
    return {"text": text, "count": count}


def test_only_shapes_worth_proposing_are_kept():
    for token in ("ajouter", "corriger", "definir", "reecrire", "mettre"):
        assert looks_like_a_verb(token) is True, token
    # Too short, or a shape French nouns and adjectives share with verbs.
    for token in ("er", "note", "page", "carte", "suite", "le"):
        assert looks_like_a_verb(token) is False, token
    # An English base form has no ending to read, so position catches it instead.
    assert looks_like_a_verb("add") is False
    assert looks_like_a_verb("convert") is False
    with pytest.raises(TypeError):
        looks_like_a_verb(None)


def test_the_census_separates_what_the_lexicon_knows_from_what_it_misses():
    asks = (
        entry("peaufiner le city builder et le rendu", 6),
        entry("harmoniser les monstres", 4),
        entry("verifier le resultat", 3),
    )
    census = unreached_verb_candidates(
        asks, predictors={"silent": Silent()}, min_count=2, top=5
    )
    assert census["asks"] == 3
    assert census["unreached_distinct"] == 3
    assert census["unreached_volume"] == 13
    shaped = census["by_shape"]
    # "verifier" is in the lexicon, the two others are not.
    assert shaped["already_declared"] == 1
    missing = [item["term"] for item in shaped["missing_top"]]
    assert "peaufiner" in missing and "harmoniser" in missing
    assert "verifier" not in missing
    # "le" and "les" are stopwords, so the positional signal skips them.
    first = [item["term"] for item in census["by_first_token"]["missing_top"]]
    assert "le" not in first
    assert census["needs_ratification"] is True
    assert "not by a tagger" in census["reading"]


def test_the_census_only_counts_asks_nothing_reaches():
    asks = (
        entry("extract the columns", 5),
        entry("peaufiner le rendu", 2),
    )
    schema = reachable_schema()
    census = unreached_verb_candidates(
        asks,
        predictors={"frame": VerbFrameSignatureBackend(schema)},
        schema=schema,
        min_count=1,
    )
    assert census["asks"] == 2
    assert census["unreached_distinct"] == 1
    assert census["unreached_volume"] == 2
    assert [item["term"] for item in census["by_shape"]["missing_top"]] == ["peaufiner"]


def test_the_census_validates_its_inputs():
    with pytest.raises(ValueError, match="at least one ask"):
        unreached_verb_candidates((), predictors={"s": Silent()})
    with pytest.raises(ValueError, match="at least one predictor"):
        unreached_verb_candidates((entry("x"),), predictors={})
    with pytest.raises(ValueError, match="min_count"):
        unreached_verb_candidates((entry("x"),), predictors={"s": Silent()}, min_count=0)


def test_a_project_name_is_a_domain_term_and_not_a_verb():
    # "Odycer" ends like an infinitive, so a shape rule alone would file it as a
    # false verb; it is vocabulary, and it belongs in the other list.
    asks = (
        entry("peaufiner le rendu de Ultimate Odycer build et VoxelPlanet", 7),
        entry("peaufiner la carte", 3),
    )
    census = unreached_verb_candidates(
        asks, predictors={"silent": Silent()}, min_count=2, top=6
    )
    verbs = [item["term"] for item in census["by_shape"]["missing_top"]]
    terms = [item["term"] for item in census["by_domain_term"]["top"]]
    assert "peaufiner" in verbs
    assert "voxelplanet" in terms
    assert "voxelplanet" not in verbs
    # The capital is what separates a name from a verb of the same shape, so the
    # project lands in the term list and stays out of the verb list.
    assert "odycer" not in verbs
    assert "odycer" in terms
    assert census["by_domain_term"]["volume"] >= 7


def test_a_name_capitalised_mid_text_is_not_a_verb_candidate():
    # "Odycer" and "auditer" are the same shape; the capital is the only signal,
    # and it is read per text rather than globally.
    asks = (
        entry("peaufiner les rendus du projet Odycer", 4),
        entry("odycer doit etre audite", 3),
    )
    census = unreached_verb_candidates(
        asks, predictors={"silent": Silent()}, min_count=1, top=8
    )
    verbs = {item["term"] for item in census["by_shape"]["missing_top"]}
    terms = {item["term"] for item in census["by_domain_term"]["top"]}
    assert "odycer" not in verbs  # capitalised mid-text in the first ask
    assert "odycer" in terms
    assert "peaufiner" in verbs
