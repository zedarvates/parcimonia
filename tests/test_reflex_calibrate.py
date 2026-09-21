from tiberium_ai.pipeline import ContinuityPipeline, PipelineContext, PipelineHalt
from tiberium_ai.continuation import QuotaMetrics
from tiberium_ai.director import AstralDirector, DirectorMode
from tiberium_ai.kanban import parse_kanban_markdown
from tiberium_ai.reflex import CalibrationSnapshot, ReflexEngine, default_reflex_questions
from tiberium_ai.reflex_calibrate import (
    HintReflexBackend,
    LabelledCase,
    calibrate_parcimonia_fixtures,
    evaluate_calibration,
)
from tiberium_ai.reflex_corpus import parcimonia_reflex_cases


def test_fixture_corpus_has_enough_labels():
    cases = parcimonia_reflex_cases()
    assert len(cases) >= 50
    assert all(case.labels.keys() == {"difficulty", "should_continue", "needs_browser"} for case in cases)


def test_fixture_calibration_never_authorizes_auto_act():
    report = calibrate_parcimonia_fixtures()
    assert report.data_origin == "fixture"
    assert report.n_cases >= 50
    assert report.authorizes_auto_act() is False

    difficulty = report.for_question("parcimonia.difficulty")
    assert difficulty is not None
    assert difficulty.measured is False
    assert difficulty.data_origin == "fixture"
    assert difficulty.n_labelled >= 50
    assert difficulty.coverage_at_threshold is not None
    assert difficulty.brier is not None
    assert difficulty.permits_auto_act(0.99) is False

    record = report.to_record()
    assert record["kind"] == "reflex_calibration"
    assert record["authorizes_auto_act"] is False
    assert record["data_origin"] == "fixture"


def test_fixture_origin_overrides_measured_flag():
    snapshot = CalibrationSnapshot(
        task_family="parcimonia.difficulty",
        measured=True,
        n_labelled=80,
        threshold=0.85,
        coverage_at_threshold=0.9,
        accuracy_at_threshold=0.99,
        brier=0.02,
        data_origin="fixture",
    )
    assert snapshot.permits_auto_act(0.99) is False


def test_hint_backend_is_deterministic():
    engine = ReflexEngine(HintReflexBackend())
    questions = default_reflex_questions()
    first = engine.evaluate("Run pytest on tests/test_verification.py", questions)
    second = engine.evaluate("Run pytest on tests/test_verification.py", questions)
    assert first.get("difficulty").choice == second.get("difficulty").choice
    assert first.get("difficulty").choice == "deterministic"
    assert first.get("needs_browser").noul < 0.5


def test_evaluate_calibration_labelled_outcomes_still_needs_bars():
    cases = (
        LabelledCase("x1", "Run pytest now", {"difficulty": "deterministic"}),
        LabelledCase("x2", "Run pytest again", {"difficulty": "deterministic"}),
    )
    report = evaluate_calibration(
        ReflexEngine(HintReflexBackend()),
        default_reflex_questions()[:1],
        cases,
        data_origin="labelled_outcomes",
        min_labelled=50,
    )
    snapshot = report.for_question("parcimonia.difficulty")
    assert snapshot is not None
    assert snapshot.measured is True
    assert snapshot.data_origin == "labelled_outcomes"
    assert snapshot.n_labelled == 2
    assert snapshot.permits_auto_act(0.99) is False


def test_pipeline_trust_reflex_stays_closed_on_fixture_snapshot():
    report = calibrate_parcimonia_fixtures()
    snapshot = report.for_question("parcimonia.should_continue")
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director, reflex=ReflexEngine(HintReflexBackend()))
    board = parse_kanban_markdown(
        """# Board
## En cours
- [ ] TASK-056 [P2] [difficulty: compact]
  - title: End-to-end continuation wiring
"""
    )
    trace = pipeline.run_once(
        board,
        PipelineContext(
            quota=QuotaMetrics(remaining_percent=80.0, window_duration_mins=300),
            trust_reflex=True,
            calibration=snapshot,
            source_text="Run pytest on the fixture suite",
        ),
    )
    assert trace.halt == PipelineHalt.UNCALIBRATED
    assert trace.counters.delivered == 0

