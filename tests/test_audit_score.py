import pytest

from tiberium_ai.audit_score import (
    PATTERN_PENALTY_CAP,
    AuditBand,
    DIMENSION_NAMES,
    DimensionValue,
    ScoreWeights,
    compute_audit_score,
)
from tiberium_ai.pattern_rules import RuleAxis, RuleFinding, RuleSeverity


def full(value=1.0):
    return [DimensionValue(name, value, 'measured ' + name) for name in DIMENSION_NAMES]


def with_value(name, value):
    return [
        DimensionValue(item, value if item == name else 1.0, 'measured ' + item)
        for item in DIMENSION_NAMES
    ]


def finding(severity=RuleSeverity.LOW, line=1):
    return RuleFinding('rule.probe', RuleAxis.HYGIENE, severity, line, 0, 'probe.one', 'one')


def test_healthy_dimensions_produce_no_deficit():
    score = compute_audit_score(full(), [])

    assert score.deficit == 0.0
    assert score.band is AuditBand.SOUND
    assert score.skipped == ()
    assert set(score.attribution) == set(DIMENSION_NAMES) | {'rule_penalty'}


def test_one_collapsed_dimension_cannot_be_averaged_away():
    score = compute_audit_score(with_value('substance', 0.5), [])

    assert 20.0 <= score.deficit < 25.0
    assert score.band is AuditBand.NOTED


def test_a_dimension_out_of_range_is_clamped_and_recorded():
    high = DimensionValue('substance', 1.4, 'm')
    low = DimensionValue('substance', -0.2, 'm')

    assert (high.value, high.clamped) == (1.0, True)
    assert (low.value, low.clamped) == (0.0, True)
    score = compute_audit_score([high, DimensionValue('import_hygiene', 1.0, 'm')], [])
    assert score.clamped == ('substance',)
    assert low.clamped


def test_weights_refuse_a_negative_or_zero_sum():
    with pytest.raises(ValueError):
        ScoreWeights(substance=-1.0)
    with pytest.raises(ValueError):
        ScoreWeights(0.0, 0.0, 0.0, 0.0)


def test_weights_refuse_an_unknown_scored_dimension():
    with pytest.raises(ValueError):
        ScoreWeights().declared_for(['vibe'])


def test_an_empty_or_duplicated_dimension_list_is_refused():
    with pytest.raises(ValueError):
        compute_audit_score([], [])
    duplicated = [DimensionValue('substance', 1.0, 'a'), DimensionValue('substance', 1.0, 'b')]
    with pytest.raises(ValueError):
        compute_audit_score(duplicated, [])


def test_a_suppression_that_was_never_measured_is_refused():
    with pytest.raises(ValueError):
        compute_audit_score(full(), [], suppressed=('substance', 'vibe'))


def test_a_suppressed_dimension_does_not_penalise_and_is_recorded():
    score = compute_audit_score(with_value('substance', 0.0), [], suppressed=('substance',))

    assert score.deficit == 0.0
    assert score.skipped == ('substance',)
    assert score.dimensions['substance'] == 1.0


def test_the_pattern_penalty_is_capped():
    findings = [finding(RuleSeverity.BLOCKER, line=index) for index in range(1, 7)]
    score = compute_audit_score(full(), findings)

    assert score.pattern_penalty == PATTERN_PENALTY_CAP
    assert score.deficit == PATTERN_PENALTY_CAP
    assert score.band is AuditBand.QUESTIONABLE


def test_a_blocker_raises_the_band_floor():
    score = compute_audit_score(full(), [finding(RuleSeverity.BLOCKER)])

    assert score.deficit == 12.0
    assert score.band is AuditBand.QUESTIONABLE


def test_three_high_findings_raise_a_sound_score_to_noted():
    findings = [finding(RuleSeverity.HIGH, line=index) for index in range(1, 4)]
    score = compute_audit_score(full(), findings)

    assert score.band is AuditBand.NOTED


def test_attribution_names_the_dimensions_and_the_rule_share():
    score = compute_audit_score(with_value('substance', 0.4), [finding(RuleSeverity.HIGH)])
    total = sum(score.attribution.values())

    assert abs(total - 1.0) < 1e-6
    assert score.attribution['rule_penalty'] > 0.0
    assert score.attribution['substance'] > score.attribution['import_hygiene']


def test_a_zero_weight_on_every_scored_dimension_is_refused():
    weights = ScoreWeights(0.0, 1.0, 1.0, 1.0)
    with pytest.raises(ValueError):
        compute_audit_score([DimensionValue('substance', 1.0, 'm')], [], weights)


def test_findings_must_be_rule_findings():
    with pytest.raises(TypeError):
        compute_audit_score(full(), [object()])


def test_a_reason_code_is_carried_into_the_result():
    score = compute_audit_score(full(), [], reason_code='nothing_to_judge')

    assert score.reason_code == 'nothing_to_judge'
    assert score.to_dict()['band'] == 'sound'


def test_scoring_is_deterministic_whatever_the_finding_order():
    forwards = [finding(RuleSeverity.HIGH, 1), finding(RuleSeverity.LOW, 2)]
    backwards = list(reversed(forwards))

    assert compute_audit_score(full(), forwards) == compute_audit_score(full(), backwards)
