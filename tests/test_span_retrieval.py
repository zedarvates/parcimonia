from tiberium_ai.signature_backends import KnnSignatureBackend, memory_from_cases
from tiberium_ai.signature_corpus import aligned_cases, example_schema, paraphrase_cases
from tiberium_ai.span_retrieval import SpanKnnSignatureBackend, frame_parts
from tiberium_ai.task_signature import calibrate_signatures, predict_signature


def _signature(prompt, backend, schema):
    return predict_signature(
        schema,
        prompt,
        predictor=backend,
        predictor_id="knn.spans",
        predictor_version="1",
    )


def test_exact_action_object_is_not_diluted_by_same_topic():
    schema = example_schema()
    memory = memory_from_cases(aligned_cases(), schema)
    prompt = aligned_cases()[0].prompt
    tokens = KnnSignatureBackend(memory)
    spans = SpanKnnSignatureBackend(memory)

    assert _signature(prompt, tokens, schema).abstained is True
    result = _signature(prompt, spans, schema)
    assert result.kind == "extract"
    assert spans.neighbours(prompt)[0][0] == 1.0


def test_same_object_different_action_is_not_a_neighbour():
    schema = example_schema()
    memory = memory_from_cases(aligned_cases(), schema)
    spans = SpanKnnSignatureBackend(memory)
    action, obj = frame_parts("format the schema of the file")
    assert action == "format"
    assert "schema" in obj
    assert all(
        frame_parts(entry.prompt)[0] == "format"
        for _, entry in spans.neighbours("format the schema of the file")
    )
    assert spans.neighbours("zzz qqq") == ()


def test_uncontested_paraphrases_are_reported_separately_from_disputed_labels():
    schema = example_schema()
    cases = paraphrase_cases()[:9]
    memory = memory_from_cases(aligned_cases(), schema)
    token_report = calibrate_signatures(
        cases,
        schema=schema,
        predictor=KnnSignatureBackend(memory),
        predictor_id="knn.tokens",
        predictor_version="1",
    )
    span_report = calibrate_signatures(
        cases,
        schema=schema,
        predictor=SpanKnnSignatureBackend(memory),
        predictor_id="knn.spans",
        predictor_version="1",
    )
    assert token_report.cases == span_report.cases == 9
    assert token_report.coverage == 1 / 9
    assert span_report.coverage == 0.0
    assert span_report.kind_agreement is None
    assert token_report.data_origin == span_report.data_origin == "fixture"
    assert token_report.threshold_authorized is False
    assert span_report.threshold_authorized is False
