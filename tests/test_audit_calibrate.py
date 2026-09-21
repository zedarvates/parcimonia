import pytest

from tiberium_ai.audit_calibrate import (
    AuditCalibrationReport,
    CaseObservation,
    RuleScore,
    calibrate_static_audit,
)
from tiberium_ai.audit_corpus import BAND_CLASSES, LabelledAuditCase, audit_corpus
from tiberium_ai.pattern_rules import (
    Rule,
    RuleAxis,
    RuleFinding,
    RuleRegistry,
    RuleSeverity,
    builtin_rule_registry,
)
from tiberium_ai.source_role import SourceRole
from tiberium_ai.source_scan import SourceScan


class FiresEverywhereRule(Rule):
    """A deliberately wrong rule: it accuses every module it sees."""

    rule_id = 'rule.fires-everywhere'
    axis = RuleAxis.HYGIENE
    severity = RuleSeverity.LOW
    description = 'reports one finding on every module'
    applies_to = frozenset({SourceRole.MODULE})

    def check(self, scan: SourceScan) -> tuple[RuleFinding, ...]:
        return (self.finding(line=1, detail_code='probe.wide', message='wide'),)


def test_the_corpus_labels_are_internally_consistent():
    cases = audit_corpus()
    identifiers = [item.case_id for item in cases]

    assert len(cases) >= 30
    assert len(set(identifiers)) == len(identifiers)
    assert all(item.band_class in BAND_CLASSES for item in cases)


def test_every_shipped_rule_is_exercised_at_least_once():
    expected = {rule_id for item in audit_corpus() for rule_id in item.rules}
    shipped = {rule.rule_id for rule in builtin_rule_registry().rules()}

    assert expected == shipped


def test_the_calibration_reproduces_every_label_on_the_corpus():
    report = calibrate_static_audit()

    assert report.n_cases == len(audit_corpus())
    assert report.role_agreement == 1.0
    assert report.band_agreement == 1.0
    assert report.rule_agreement == 1.0
    assert report.disagreements == ()


def test_per_rule_precision_and_recall_are_measured_not_assumed():
    report = calibrate_static_audit()

    assert report.per_rule
    for score in report.per_rule:
        assert score.precision == 1.0
        assert score.recall == 1.0
        assert score.expected_in >= 1
        assert score.missed == 0


def test_a_narrowed_rule_set_shows_up_as_missed_detections():
    narrowed = builtin_rule_registry()
    narrowed.disable('rule.inflated-claim')
    report = calibrate_static_audit(registry=narrowed)

    scores = {score.rule_id: score for score in report.per_rule}
    assert 'rule.inflated-claim' not in scores
    assert report.rule_agreement < 1.0
    assert report.disagreements


def test_a_widened_rule_shows_up_as_a_false_positive():
    wide = RuleRegistry([FiresEverywhereRule()])
    report = calibrate_static_audit(registry=wide)

    score = report.per_rule[0]
    assert score.false_positives > 0
    assert score.precision == 0.0
    assert score.recall is None


def test_a_fixture_report_never_authorizes_a_threshold():
    report = calibrate_static_audit()

    assert report.data_origin == 'fixture'
    assert report.authorizes_threshold() is False
    assert report.to_record()['threshold_authorized'] is False
    assert 'measured' in report.to_record()['threshold_authorized_reason']


def test_a_fixture_report_cannot_declare_itself_authorized():
    with pytest.raises(ValueError):
        AuditCalibrationReport(
            data_origin='fixture',
            policy_base='static-audit-v1',
            policy_version='static-audit-v1+rules:0f',
            rule_fingerprint='0f',
            declared_weights={'substance': 1.0},
            cases=(),
            per_rule=(),
            threshold_authorized=True,
        )


def test_the_calibration_is_deterministic():
    first = calibrate_static_audit()
    second = calibrate_static_audit()

    assert first.to_record() == second.to_record()
    assert first.case_records() == second.case_records()


def test_the_record_carries_the_policy_and_the_declared_weights():
    record = calibrate_static_audit().to_record()

    assert record['kind'] == 'audit_calibration'
    assert record['policy_version'].endswith(builtin_rule_registry().fingerprint())
    assert sum(record['declared_weights'].values()) == pytest.approx(1.0)


def test_an_unknown_band_class_is_refused():
    with pytest.raises(ValueError):
        LabelledAuditCase('x', 'src/x.py', 'x = 1', 'module', 'whatever', (), 'r')


def test_a_calibration_needs_at_least_one_case():
    with pytest.raises(ValueError):
        calibrate_static_audit(cases=[])


def test_shared_helpers_reject_an_empty_case_list():
    score = RuleScore('rule.x', 0, 0, 0, 0)

    assert score.precision is None
    assert score.recall is None
    assert score.fired_in == 0
