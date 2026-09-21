import pytest

from tiberium_ai.pattern_rules import (
    FINDING_CAP,
    Rule,
    RuleAxis,
    RuleFinding,
    RuleRegistry,
    RuleSeverity,
    builtin_rule_registry,
)
from tiberium_ai.source_role import SourceRole
from tiberium_ai.source_scan import scan_source


class ProbeRule(Rule):
    rule_id = 'rule.probe'
    axis = RuleAxis.HYGIENE
    severity = RuleSeverity.LOW
    description = 'always reports one finding on line 1'
    applies_to = frozenset({SourceRole.MODULE})

    def check(self, scan):
        return (self.finding(line=1, detail_code='probe.one', message='one'),)


class LouderProbeRule(ProbeRule):
    rule_id = 'rule.probe'
    severity = RuleSeverity.HIGH


def source_of(*lines: str) -> str:
    return '\n'.join(lines)


def run(source, role=SourceRole.MODULE, path='sample.py'):
    return builtin_rule_registry().run(scan_source(path, source), role)


def test_registering_the_same_rule_id_twice_is_refused():
    registry = RuleRegistry([ProbeRule()])
    with pytest.raises(ValueError):
        registry.register(ProbeRule())


def test_a_registry_refuses_something_that_is_not_a_rule():
    with pytest.raises(TypeError):
        RuleRegistry([object()]).register(object())


def test_a_rule_without_an_id_is_refused():
    class Anonymous(Rule):
        def check(self, scan):
            return ()

    with pytest.raises(ValueError):
        RuleRegistry([Anonymous()])


def test_enabling_and_disabling_require_a_known_id():
    registry = RuleRegistry([ProbeRule()])
    with pytest.raises(ValueError):
        registry.disable('rule.unknown')
    registry.disable('rule.probe')
    assert len(registry) == 0
    assert registry.rules() == ()
    registry.enable('rule.probe')
    assert len(registry) == 1


def test_rules_are_returned_in_a_stable_order():
    identifiers = [rule.rule_id for rule in builtin_rule_registry().rules()]
    assert identifiers == sorted(identifiers)


def test_a_disabled_rule_does_not_run():
    source = source_of('# TODO: later')
    scan = scan_source('sample.py', source)
    registry = builtin_rule_registry()
    assert registry.run(scan, SourceRole.MODULE)
    registry.disable('rule.placeholder-marker')
    assert registry.run(scan, SourceRole.MODULE) == ()


def test_a_rule_only_runs_on_the_roles_it_applies_to():
    assert run(source_of('# TODO: later'), SourceRole.TEST) == ()


def test_findings_are_returned_in_file_order():
    source = source_of('x = 1', '# TODO: second', '', '# TODO: first')
    findings = run(source)
    assert [finding.line for finding in findings] == [2, 4]


def test_the_fingerprint_changes_with_severity_and_with_disabling():
    base = RuleRegistry([ProbeRule()]).fingerprint()
    assert base == RuleRegistry([ProbeRule()]).fingerprint()
    assert base != RuleRegistry([LouderProbeRule()]).fingerprint()
    disabled = RuleRegistry([ProbeRule()])
    disabled.disable('rule.probe')
    assert base != disabled.fingerprint()


def test_a_finding_refuses_malformed_input():
    with pytest.raises(ValueError):
        RuleFinding('', RuleAxis.HYGIENE, RuleSeverity.LOW, 1, 0, 'x', 'x')
    with pytest.raises(TypeError):
        RuleFinding('r', 'hygiene', RuleSeverity.LOW, 1, 0, 'x', 'x')
    with pytest.raises(ValueError):
        RuleFinding('r', RuleAxis.HYGIENE, RuleSeverity.LOW, -1, 0, 'x', 'x')


def test_a_finding_serialises_its_identity():
    finding = ProbeRule().finding(line=3, detail_code='probe.one', message='one')
    record = finding.to_dict()
    assert record['rule_id'] == 'rule.probe'
    assert record['axis'] == 'hygiene'
    assert record['severity'] == 'low'
    assert (record['line'], record['column']) == (3, 0)




def test_a_repeated_marker_is_capped():
    lines = ['# TODO: item %d' % index for index in range(FINDING_CAP + 4)]
    assert len(run(source_of(*lines))) == FINDING_CAP


def test_a_bare_handler_and_a_pass_only_handler_are_reported():
    bare = source_of('try:', '    pass', 'except:', '    pass')
    typed = source_of('try:', '    pass', 'except ValueError:', '    pass')
    assert [f.detail_code for f in run(bare)] == ['except.bare', 'except.silent']
    assert [f.detail_code for f in run(typed)] == ['except.silent']


def test_deliberate_control_flow_in_a_handler_is_left_alone():
    looping = source_of('for item in (1,):', '    try:', '        pass', '    except ValueError:', '        continue')
    returning = source_of('def f():', '    try:', '        return 1', '    except ValueError:', '        return None')
    assert run(looping) == ()
    assert run(returning) == ()


def test_leftover_debug_output_is_reported_but_not_in_a_script():
    source = source_of('import pdb', '', '', 'def f():', '    print(1)', '    breakpoint()', '    pdb.set_trace()')
    codes = sorted(finding.detail_code for finding in run(source))
    assert codes == ['emit.breakpoint', 'emit.print', 'emit.set_trace']
    assert run(source, SourceRole.SCRIPT) == ()


def test_a_marketing_register_is_reported_in_a_comment_or_a_docstring():
    comment = run(source_of('# A production-ready module'))
    docstring = run(source_of('"""A blazing fast module."""'))
    assert [f.detail_code for f in comment] == ['claim.production-ready']
    assert [f.detail_code for f in docstring] == ['claim.blazing-fast']
    assert run(source_of('# production-ready'), SourceRole.TEST) == ()
def test_a_placeholder_marker_is_found_in_a_comment_only():
    findings = run(source_of('# TODO: replace me'))
    assert [finding.detail_code for finding in findings] == ['marker.todo']
    assert run(source_of('"""TODO: replace me"""')) == ()


def test_an_exception_class_name_is_not_a_deferred_work_marker():
    assert run(source_of('# see NotImplementedError for the contract')) == ()
    marker = run(source_of('# TODO: raise NotImplementedError'))
    assert [finding.detail_code for finding in marker] == ['marker.todo']
