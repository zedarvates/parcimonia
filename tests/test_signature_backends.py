import pytest

from tiberium_ai.reflex import InjectedReflexBackend, ReflexKind, ReflexQuestion
from tiberium_ai.signature_backends import (
    MIN_TOLERANT_LENGTH,
    KnnSignatureBackend,
    LayeredSignatureBackend,
    SignatureMemoryEntry,
    VerbFrameSignatureBackend,
    memory_from_cases,
    normalise_text,
    tokens_of,
    verb_action,
)
from tiberium_ai.signature_corpus import (
    aligned_cases,
    example_schema,
    paraphrase_cases,
)
from tiberium_ai.public_corpus import public_schema
from tiberium_ai.real_asks import reachable_schema
from tiberium_ai.task_signature import (
    DeclaredItem,
    RuleBasedSignatureBackend,
    SignatureSchema,
    calibrate_signatures,
    predict_signature,
)

PREDICTOR_VERSION = "1"


def calibrate(label, predictor, cases, schema=None):
    return calibrate_signatures(
        cases,
        schema=schema or example_schema(),
        predictor=predictor,
        predictor_id=label,
        predictor_version=PREDICTOR_VERSION,
    )


def frame(schema=None):
    return VerbFrameSignatureBackend(schema or example_schema())


def small_schema():
    return SignatureSchema(
        name="small",
        kinds=(DeclaredItem("extract", ("extract",)), DeclaredItem("format", ("format",))),
        capabilities=(DeclaredItem("route.knn", ("similar case",)),),
        fields=(DeclaredItem("path", ("file", "path")), DeclaredItem("schema", ("schema",))),
    )


def predict(prompt, predictor, schema=None):
    active = schema or example_schema()
    return predict_signature(
        active,
        prompt,
        predictor=predictor,
        predictor_id="test",
        predictor_version=PREDICTOR_VERSION,
    )


# --- normalisation --------------------------------------------------------


def test_normalisation_strips_accents_and_keeps_alphanumeric_runs():
    assert normalise_text("Récupère les Colonnes d'un CSV !") == (
        "recupere les colonnes d un csv"
    )
    assert tokens_of("Before, the file:") == ("before", "the", "file")
    assert normalise_text("") == ""
    with pytest.raises(TypeError, match="string"):
        normalise_text(7)


# --- the frame ------------------------------------------------------------


def test_the_head_verb_gives_the_action_in_both_languages():
    assert predict("extract the schema", frame()).kind == "extract"
    assert predict("sors-moi les colonnes", frame()).kind == "extract"
    assert predict("mets ce tableau au propre", frame()).kind == "format"
    assert predict("contrôle la cohérence", frame()).kind == "verify"


def test_span_position_removes_the_accidental_deadline():
    # The keyword rule reads the preposition before as a deadline hint; the frame
    # sees a span delimiter, so no field is declared.
    assert predict("reformat the options before deciding", frame()).fields == ()
    assert predict("reformat the options before deciding", RuleBasedSignatureBackend(example_schema())).fields == ("deadline",)


def test_a_hint_outside_every_span_is_worth_nothing():
    # The schema word sits before the verb, where a deliverable does not live.
    signature = predict("the schema file should be parsed", frame(), small_schema())
    assert signature.kind == "extract"
    assert signature.fields == ()


def test_a_hint_in_an_adjunct_still_counts():
    signature = predict("extract the columns from the file", frame(), small_schema())
    # The object span carries the deliverable, the adjunct carries the source,
    # and the two are not worth the same.
    assert signature.fields == ("path", "schema")
    assert signature.field_scores["schema"] == 1.0
    assert signature.field_scores["path"] == 0.8


def test_an_undeclared_action_abstains_instead_of_borrowing_a_kind():
    narrow = SignatureSchema(
        name="narrow",
        kinds=(DeclaredItem("alpha", ("alpha",)), DeclaredItem("beta", ("beta",))),
    )
    signature = predict("verify the file", frame(narrow), narrow)
    assert signature.abstained is True
    assert signature.kind is None


def test_without_a_head_verb_there_is_no_frame():
    signature = predict("les colonnes de ce CSV", frame())
    assert signature.abstained is True
    assert signature.fields == ()


def test_the_goal_is_read_from_the_object_or_an_adjunct():
    assert predict("choose the cheapest mechanism", frame()).goal == "GOAL-PARCIMONIA"
    assert predict("extract the columns for the routing cost", frame()).goal == "GOAL-PARCIMONIA"
    assert predict("extract the columns", frame()).goal is None


def test_the_frame_refuses_a_foreign_schema():
    with pytest.raises(TypeError, match="SignatureSchema"):
        VerbFrameSignatureBackend("not a schema")
    with pytest.raises(TypeError, match="boolean"):
        VerbFrameSignatureBackend(example_schema(), latin_only="yes")
    with pytest.raises(TypeError, match="interrogative_signal"):
        VerbFrameSignatureBackend(example_schema(), interrogative_signal="yes")


# --- one typo away -------------------------------------------------------


def test_a_typo_one_edit_away_still_names_an_action():
    # One insertion, and one adjacent transposition.
    assert verb_action("formatter") == ("format", False)
    assert verb_action("corrgier") == ("format", False)
    assert predict("formatter le tableau", frame(), example_schema()).kind == "format"
    assert predict("corrgier le bug", frame(), example_schema()).kind == "format"
    # Two edits away is not a slip, it is a variant: it is declared, not guessed.
    assert verb_action("develloper") == ("generate", True)
    # The example schema declares no generate kind, so the reachable one is used.
    signature = predict(
        "develloper le city builder",
        VerbFrameSignatureBackend(reachable_schema()),
        reachable_schema(),
    )
    assert signature.kind == "generate"


def test_an_exact_verb_always_wins_over_a_tolerated_one():
    # Tolerance only runs when nothing exact was found, so the later exact verb
    # decides and the typo cannot outrank it.
    assert verb_action("corriger") == ("format", True)
    assert verb_action("corrgier") == ("format", False)
    schema = reachable_schema()
    signature = predict(
        "corrgier puis verifier le resultat",
        VerbFrameSignatureBackend(schema),
        schema,
    )
    assert signature.kind == "verify"


def test_a_short_token_is_never_stretched_into_a_verb():
    assert MIN_TOLERANT_LENGTH == 6
    assert verb_action("fai") is None
    # "rendu" is one substitution from "rends", which is why the floor is six.
    assert verb_action("rendu") is None
    assert predict("fai le city", frame(), example_schema()).abstained is True


def test_tolerance_belongs_to_the_frame_and_not_to_the_lexical_baseline():
    # The rule stays a strict baseline on purpose: its weakness on a typo is part
    # of what it is, and hiding it would flatter the comparison.
    signature = predict(
        "develloper le city builder",
        RuleBasedSignatureBackend(example_schema()),
        example_schema(),
    )
    assert signature.abstained is True


def test_verb_action_reports_exactness_and_validates_its_input():
    with pytest.raises(TypeError, match="string"):
        verb_action(7)
    assert verb_action("extract") == ("extract", True)
    assert verb_action("extract", tolerant=False) == ("extract", True)
    assert verb_action("zzzzzzzz", tolerant=False) is None


def test_the_last_two_verbs_a_real_census_asked_for_are_declared():
    # Declared because a census of the author's own asks found them missing; they
    # close the verb list, which now carries only noise to reject.
    assert verb_action("finir") == ("generate", True)
    assert verb_action("jouer") == ("generate", True)


# --- the interrogative signal --------------------------------------------


def public_frame(*, interrogative_signal=True):
    return VerbFrameSignatureBackend(
        public_schema(), interrogative_signal=interrogative_signal
    )


def test_a_question_without_a_head_verb_is_read_as_an_ask_for_an_answer():
    for prompt in (
        "what is the capital of France",
        "why do cats purr",
        "how does a fridge work",
        "quel est le prix du billet",
        "pourquoi le ciel est bleu",
    ):
        signature = predict(prompt, public_frame(), public_schema())
        assert signature.kind == "answer", prompt


def test_the_signal_defers_to_a_head_verb_when_the_sentence_carries_one():
    signature = predict(
        "can you summarise this article", public_frame(), public_schema()
    )
    assert signature.kind == "summarise"


def test_the_signal_is_the_only_difference_from_the_control_arm():
    question = "what is the capital of France"
    treatment = predict(question, public_frame(), public_schema())
    control = predict(
        question, public_frame(interrogative_signal=False), public_schema()
    )
    assert treatment.kind == "answer"
    assert control.abstained is True


def test_the_signal_does_nothing_when_no_answer_kind_is_declared():
    # The example vocabulary has no answer kind, so the fallback cannot borrow
    # one and the frame abstains exactly as it did before the signal existed.
    signature = predict("what is the capital of France", frame(), example_schema())
    assert signature.abstained is True


def test_the_authored_bench_is_unchanged_by_the_signal():
    schema = example_schema()
    before = calibrate(
        "frame.control",
        VerbFrameSignatureBackend(schema, interrogative_signal=False),
        paraphrase_cases(),
        schema,
    )
    after = calibrate("frame.interrogative", frame(schema), paraphrase_cases(), schema)
    assert before.coverage == after.coverage
    assert before.kind_agreement == after.kind_agreement
    assert before.field_recall == after.field_recall


def test_a_word_that_only_looks_like_a_question_still_abstains():
    # The marker is the first token, not any token: this is the documented limit
    # of a cheap rule, and the honest reading of a bare question mark.
    signature = predict("really", public_frame(), public_schema())
    assert signature.abstained is True


# --- the specificity tie-break, kept as a measured negative ------------------


def specificity_frame():
    return VerbFrameSignatureBackend(public_schema(), specificity_tie_break=True)


def test_a_specific_hint_beats_the_generic_question_marker():
    signature = predict(
        "what are some ideas for a cafe name", specificity_frame(), public_schema()
    )
    assert signature.kind == "propose"


def test_without_the_tie_break_the_same_question_is_an_answer_request():
    signature = predict(
        "what are some ideas for a cafe name", public_frame(), public_schema()
    )
    assert signature.kind == "answer"


def test_the_tie_break_is_off_by_default_because_it_earned_nothing():
    assert VerbFrameSignatureBackend(public_schema()).specificity_tie_break is False
    # It never changes a question that carries no specific hint.
    question = "what is the capital of France"
    assert predict(question, specificity_frame(), public_schema()).kind == "answer"
    assert predict(question, public_frame(), public_schema()).kind == "answer"


def test_an_ambiguous_specific_match_abstains_instead_of_picking_one():
    schema = SignatureSchema(
        name="tie",
        kinds=(
            DeclaredItem("alpha", ("alpha",)),
            DeclaredItem("bravo", ("bravo",)),
            DeclaredItem("answer", ("what", "why")),
        ),
    )
    backend = VerbFrameSignatureBackend(schema, specificity_tie_break=True)
    signature = predict("what about alpha and bravo", backend, schema)
    assert signature.abstained is True


def test_an_interrogative_hint_is_not_specific_enough_to_win():
    # The answer kind's own question words must never win the specificity
    # comparison, or the generic marker would beat the very hints that describe
    # what the ask wants. Nothing here is a lexicon verb, so the fallback path is
    # the one being exercised.
    signature = predict(
        "which idea is the best", specificity_frame(), public_schema()
    )
    assert signature.kind == "propose"


# --- the layered route ----------------------------------------------------


KIND_QUESTION = ReflexQuestion(
    "kind", ReflexKind.CHOICE, "Which kind?", criteria={"a": "a", "b": "b"}
)
FIELD_QUESTION = ReflexQuestion("field.x", ReflexKind.NOUL, "Is x provided?")


def choice_answer(probabilities, chosen=None):
    keys = list(probabilities)
    return {
        "choice": chosen or max(keys, key=lambda key: probabilities[key]),
        "probabilities": probabilities,
        "confidence": None,
    }


def noul_answer(probability):
    return {
        "noul": probability,
        "probabilities": {"false": 1.0 - probability, "true": probability},
        "confidence": None,
    }


def layered(primary_answers, fallback_answers, **overrides):
    arguments = {"primary_floor": 0.9}
    arguments.update(overrides)
    return LayeredSignatureBackend(
        primary=InjectedReflexBackend(answers=primary_answers),
        fallback=InjectedReflexBackend(answers=fallback_answers),
        **arguments,
    )


def test_the_primary_decides_where_it_is_certain():
    backend = layered(
        {"kind": choice_answer({"a": 1.0, "b": 0.0})},
        {"kind": choice_answer({"a": 0.0, "b": 1.0})},
    )
    answers = backend.evaluate("text", (KIND_QUESTION,))
    assert answers["kind"]["choice"] == "a"


def test_the_fallback_decides_where_the_primary_is_not_certain():
    backend = layered(
        {"kind": choice_answer({"a": 0.5, "b": 0.5})},
        {"kind": choice_answer({"a": 0.0, "b": 1.0})},
    )
    answers = backend.evaluate("text", (KIND_QUESTION,))
    assert answers["kind"]["choice"] == "b"


def test_the_choice_is_per_question_not_per_input():
    # The primary cannot settle the act but it settles the field, so the two
    # mechanisms each decide what they actually know.
    backend = layered(
        {
            "kind": choice_answer({"a": 0.5, "b": 0.5}),
            "field.x": noul_answer(1.0),
        },
        {
            "kind": choice_answer({"a": 1.0, "b": 0.0}),
            "field.x": noul_answer(0.0),
        },
    )
    answers = backend.evaluate("text", (KIND_QUESTION, FIELD_QUESTION))
    assert answers["kind"]["choice"] == "a"
    assert answers["field.x"]["noul"] == 1.0


def test_a_confident_no_is_as_certain_as_a_confident_yes():
    backend = layered(
        {"field.x": noul_answer(0.0)},
        {"field.x": noul_answer(1.0)},
    )
    answers = backend.evaluate("text", (FIELD_QUESTION,))
    assert answers["field.x"]["noul"] == 0.0


def test_the_floor_boundary_is_inclusive_and_validated():
    backend = layered(
        {"kind": choice_answer({"a": 0.9, "b": 0.1})},
        {"kind": choice_answer({"a": 0.0, "b": 1.0})},
    )
    assert backend.evaluate("text", (KIND_QUESTION,))["kind"]["choice"] == "a"
    with pytest.raises(ValueError, match="primary_floor"):
        layered({}, {}, primary_floor=1.5)
    with pytest.raises(TypeError, match="evaluate"):
        LayeredSignatureBackend(primary=object(), fallback=object())
    with pytest.raises(TypeError, match="latin_only"):
        LayeredSignatureBackend(
            primary=InjectedReflexBackend(answers={}),
            fallback=InjectedReflexBackend(answers={}),
            latin_only="yes",
        )


# --- the retrieval backend ------------------------------------------------


def memory_backend(cases=None, **overrides):
    schema = example_schema()
    arguments = {"k": 3, "min_similarity": 0.2}
    arguments.update(overrides)
    return KnnSignatureBackend(
        memory_from_cases(cases or aligned_cases(), schema), **arguments
    )


def test_memory_writes_only_what_the_labels_state():
    entries = memory_from_cases(aligned_cases()[:1], example_schema())
    answers = entries[0].answers
    assert answers["kind"]["choice"] == "extract"
    assert answers["field.path"]["noul"] == 1.0
    assert answers["field.schema"]["noul"] == 1.0
    assert answers["field.deadline"]["noul"] == 0.0
    # Capabilities carry no label, so the memory stays silent about them.
    assert answers["capability.route.knn"]["noul"] == 0.0


def test_memory_refuses_an_undeclared_kind():
    from tiberium_ai.task_signature import SignatureCase

    with pytest.raises(ValueError, match="undeclared kind"):
        memory_from_cases(
            (SignatureCase("c1", "extract the file", "unknown"),), example_schema()
        )


def test_neighbours_respect_the_floor_and_the_k():
    backend = memory_backend()
    found = backend.neighbours("extract the schema of the file at this path")
    assert found
    assert len(found) <= 3
    assert found[0][0] == 1.0
    assert backend.neighbours("zzz qqq") == ()
    # A partial overlap is not a neighbour at a strict floor...
    assert memory_backend(min_similarity=0.9).neighbours("extract the schema") == ()
    # ...while an exact input still is, at almost any floor.
    assert (
        memory_backend(min_similarity=0.99).neighbours(
            "extract the schema of the file at this path"
        )
        != ()
    )


def test_an_exact_self_match_is_diluted_by_topically_similar_neighbours():
    # The memory holds this exact input, and it still abstains: two neighbours
    # that only share the topic words carry another kind and pull the average
    # from 1.0 to 0.625. A token overlap cannot tell the same task from the same
    # subject, which is the metric's fault, not the strategy's.
    signature = predict(
        "extract the schema of the file at this path", memory_backend()
    )
    assert signature.abstained is True
    assert signature.kind_confidence == pytest.approx(0.625, abs=0.001)


def test_a_stricter_floor_recovers_the_exact_match_and_still_refuses_strangers():
    strict = memory_backend(min_similarity=0.5)
    signature = predict("extract the schema of the file at this path", strict)
    assert signature.kind == "extract"
    assert signature.kind_confidence == 1.0
    assert predict("zzz qqq www", strict).abstained is True


def test_averaging_two_different_kinds_dilutes_below_the_threshold():
    from tiberium_ai.task_signature import SignatureCase

    cases = (
        SignatureCase("a", "extract the alpha thing", "extract"),
        SignatureCase("b", "format the alpha thing", "format"),
    )
    schema = SignatureSchema(
        name="dilution",
        kinds=(DeclaredItem("extract", ("extract",)), DeclaredItem("format", ("format",))),
    )
    backend = KnnSignatureBackend(
        memory_from_cases(cases, schema), k=2, min_similarity=0.1
    )
    signature = predict("alpha thing", backend, schema)
    assert signature.abstained is True
    assert signature.kind_confidence == 0.5


def test_the_retrieval_backend_validates_its_parameters():
    schema = example_schema()
    entries = memory_from_cases(aligned_cases(), schema)
    with pytest.raises(ValueError, match="positive integer"):
        KnnSignatureBackend(entries, k=0)
    with pytest.raises(ValueError, match="min_similarity"):
        KnnSignatureBackend(entries, min_similarity=1.5)
    with pytest.raises(TypeError, match="SignatureMemoryEntry"):
        KnnSignatureBackend(("not an entry",))
    with pytest.raises(ValueError, match="nonempty"):
        SignatureMemoryEntry("", "prompt", {"kind": {}})


# --- the finding on the bench --------------------------------------------


def test_the_frame_triples_coverage_and_earns_a_kind_where_the_rule_cannot():
    schema = example_schema()
    rule = calibrate("rule", RuleBasedSignatureBackend(schema), paraphrase_cases(), schema)
    framed = calibrate("frame", frame(schema), paraphrase_cases(), schema)
    assert rule.coverage == pytest.approx(0.25)
    assert rule.kind_agreement == 0.0
    assert framed.coverage == pytest.approx(0.75)
    assert framed.kind_agreement == pytest.approx(0.667, abs=0.001)


def test_the_frame_keeps_its_own_vocabulary_intact():
    schema = example_schema()
    framed = calibrate("frame", frame(schema), aligned_cases(), schema)
    assert framed.coverage == 1.0
    assert framed.kind_agreement == 1.0
    assert framed.field_precision == 1.0
    assert framed.field_recall == 1.0


def test_the_frame_does_not_buy_the_vocabulary():
    # Structure carries the act; the declared hints are still English, so the
    # French paraphrases give the action and lose the fields. That gap is what
    # the artefact step exists to close, not another structural rule.
    schema = example_schema()
    framed = calibrate("frame", frame(schema), paraphrase_cases(), schema)
    assert framed.field_recall == 0.0
    assert framed.field_precision is None


def test_the_rule_invents_a_field_where_the_frame_invents_nothing():
    schema = example_schema()
    rule = calibrate("rule", RuleBasedSignatureBackend(schema), paraphrase_cases(), schema)
    framed = calibrate("frame", frame(schema), paraphrase_cases(), schema)
    assert rule.field_precision == 0.0
    assert framed.field_precision is None


def test_the_retrieval_backend_is_accurate_on_its_memory_and_mute_off_it():
    schema = example_schema()
    backend = memory_backend()
    aligned = calibrate("knn", backend, aligned_cases(), schema)
    paraphrased = calibrate("knn", backend, paraphrase_cases(), schema)
    # It reproduces its own memory's labels when it answers at all...
    assert aligned.kind_agreement == 1.0
    # ...but it abstains on nearly half of that same memory, because a token
    # overlap cannot separate two near-identical phrasings that carry different
    # labels, and off distribution it has almost nothing to retrieve.
    assert aligned.coverage == pytest.approx(0.583, abs=0.01)
    assert paraphrased.coverage == pytest.approx(0.167, abs=0.01)
    assert paraphrased.kind_agreement == 0.5


def test_the_three_candidates_are_ordered_by_coverage_off_distribution():
    schema = example_schema()
    rule = calibrate("rule", RuleBasedSignatureBackend(schema), paraphrase_cases(), schema)
    framed = calibrate("frame", frame(schema), paraphrase_cases(), schema)
    retrieval = calibrate("knn", memory_backend(), paraphrase_cases(), schema)
    assert framed.coverage > rule.coverage > retrieval.coverage
