import pytest

from tiberium_ai.signature_taxonomy import (
    RESPONSIBILITY,
    classify_prompt,
    multi_ask_candidates,
    partition_prompts,
    propose_taxonomy,
    responsible_layer,
)


def entry(text, count=1):
    return {"text": text, "count": count}


def test_a_whole_text_continuation_is_recognised_whatever_the_punctuation():
    for text in ("continuer", "Continuer", "oui !", "OK.", "on continue"):
        family, rule = classify_prompt(text)
        assert family == "continuation", text
        assert rule == "whole_text_term", text


def test_a_short_text_without_an_action_is_only_a_loose_continuation():
    family, rule = classify_prompt("et la suite")
    assert family == "continuation"
    assert rule == "short_without_action"
    # A terse ask lands here too, which is why the corpus reports both readings.
    assert classify_prompt("les maps ?")[1] == "short_without_action"


def test_a_short_text_with_an_action_is_an_ask():
    family, rule = classify_prompt("summarise")
    assert family == "ask"
    assert rule == "carries_an_action"
    assert classify_prompt("extract the columns and the schema")[0] == "ask"


def test_classification_uses_a_validated_horizon():
    with pytest.raises(ValueError, match="max_continuation_chars"):
        classify_prompt("continuer", max_continuation_chars=0)
    with pytest.raises(TypeError, match="string"):
        classify_prompt(7)


def test_the_partition_reports_both_readings_and_the_shares():
    prompts = (
        entry("continuer", 10),
        entry("et la suite", 3),
        entry("summarise the report", 5),
        entry("les maps ?", 2),
    )
    report = partition_prompts(prompts)
    assert report["distinct_prompts"] == 4
    assert report["total_volume"] == 20
    assert report["strict_continuation"] == {"distinct": 1, "volume": 10}
    assert report["loose_continuation"] == {"distinct": 3, "volume": 15}
    assert report["ask"] == {"distinct": 1, "volume": 5}
    assert report["ask_share_of_volume"] == 0.25
    assert report["loose_share_of_volume"] == 0.75
    with pytest.raises(ValueError, match="at least one prompt"):
        partition_prompts(())


def test_two_actions_or_two_connectives_bound_the_multi_work_candidates():
    prompts = (
        entry("extract the columns and then summarise them", 3),
        entry("format the output and tidy it then send it", 2),
        entry("summarise this", 5),
    )
    report = multi_ask_candidates(prompts)
    assert report["several_work_candidates"] == {"distinct": 2, "volume": 5}
    assert report["single_work"] == {"distinct": 1, "volume": 5}
    assert report["several_share_of_volume"] == 0.5
    assert "upper bound" in report["reading"]
    with pytest.raises(ValueError, match="at least one prompt"):
        multi_ask_candidates(())


def test_the_hint_proposal_counts_weights_and_reports_what_it_misses():
    prompts = (
        entry("summarise the report carefully", 2),
        entry("summarise the report again", 1),
        entry("extract the column names from the table", 1),
        entry("hello there", 4),
    )
    report = propose_taxonomy(prompts, max_hints=3, min_hint_count=2)
    assert report["total_volume"] == 8
    assert report["action_volume"] == {"extract": 1, "summarise": 3}
    assert report["unreached"] == {
        "distinct": 1,
        "volume": 4,
        "share_of_volume": 0.5,
    }
    hints = report["proposed_hints"]["summarise"]
    assert [item["hint"] for item in hints] == ["report", "carefully"]
    assert hints[0]["weight"] == 3
    # Every extract-side term occurs once, below the floor.
    assert report["proposed_hints"]["extract"] == []
    assert report["needs_ratification"] is True
    assert "not derived from" in report["reading"]


def test_a_word_common_to_every_action_is_not_proposed():
    prompts = (
        entry("summarise the report carefully", 2),
        entry("summarise the report again", 1),
        entry("write the report about articles", 3),
    )
    report = propose_taxonomy(prompts, max_hints=4, min_hint_count=1)
    summarise = {item["hint"] for item in report["proposed_hints"]["summarise"]}
    # "report" is frequent in this action and just as frequent outside it, so it
    # discriminates nothing and is dropped; "carefully" separates the two.
    assert "report" not in summarise
    assert "carefully" in summarise
    assert report["proposed_hints"]["summarise"][0]["hint"] == "carefully"
    # Two of the three summarise messages carry it, and none of the others do.
    assert report["proposed_hints"]["summarise"][0]["discrimination"] == pytest.approx(
        0.6667, abs=0.001
    )


def test_the_proposal_excludes_stopwords_verbs_and_tiny_tokens():
    prompts = (entry("write the article and the blog post and the page", 5),)
    report = propose_taxonomy(prompts, min_hint_count=1)
    hints = {item["hint"] for item in report["proposed_hints"]["generate"]}
    assert hints == {"article", "blog", "post", "page"}
    assert "the" not in hints and "and" not in hints


def test_the_proposal_validates_its_bounds():
    prompts = (entry("summarise the report", 1),)
    with pytest.raises(ValueError, match="max_hints"):
        propose_taxonomy(prompts, max_hints=0)
    with pytest.raises(ValueError, match="min_hint_count"):
        propose_taxonomy(prompts, min_hint_count=0)
    with pytest.raises(ValueError, match="at least one prompt"):
        propose_taxonomy(())


# --- who owns a family ----------------------------------------------------


def test_a_continuation_belongs_to_the_director_and_a_continuation_is_state():
    layer, inputs = responsible_layer("continuation")
    assert layer == "director"
    assert "quota" in inputs and "time_budget" in inputs and "stalls" in inputs
    # A continuation is arbitrated from state: no signature, no verifier, because
    # there is no ask in the text to verify.
    assert "signature" not in inputs and "verifier" not in inputs


def test_an_ask_belongs_to_parcimonia():
    layer, inputs = responsible_layer("ask")
    assert layer == "parcimonia"
    assert inputs == ("signature", "capabilities", "verifier")


def test_the_boundary_follows_the_classification():
    for text in ("continuer", "oui !", "et la suite"):
        family, _ = classify_prompt(text)
        assert responsible_layer(family)[0] == "director"
    for text in ("summarise the report", "extraire les colonnes"):
        family, _ = classify_prompt(text)
        assert responsible_layer(family)[0] == "parcimonia"


def test_an_undeclared_family_has_no_owner():
    with pytest.raises(ValueError, match="has no owner"):
        responsible_layer("chore")
    assert set(RESPONSIBILITY) == {"continuation", "ask"}
