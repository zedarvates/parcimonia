from tiberium_ai.continuation import QuotaMetrics, RouteKind
from tiberium_ai.director import AstralDirector, DirectorMode
from tiberium_ai.escalation import Budget, EscalationPolicy, EscalationState
from tiberium_ai.kanban import parse_kanban_markdown
from tiberium_ai.task_signature import DeclaredItem, RuleBasedSignatureBackend, SignatureSchema
from tiberium_ai.turn_dispatch import TurnFamily, dispatch_turn


def _board():
    return parse_kanban_markdown(
        "# Board\n## En cours\n"
        "- [ ] TASK-1 [P2] [difficulty: deterministic]\n"
        "  - title: Finish the local verifier\n"
    )


def _quota():
    return QuotaMetrics(remaining_percent=70, window_duration_mins=300)


def _signature_inputs():
    schema = SignatureSchema(
        name="turn-ask",
        kinds=(
            DeclaredItem("extract", ("extract",)),
            DeclaredItem("format", ("format",)),
        ),
    )
    return {
        "schema": schema,
        "predictor": RuleBasedSignatureBackend(schema),
        "predictor_id": "rule.signature",
        "predictor_version": "1",
        "policy": EscalationPolicy(Budget(max_cost=10, max_escalations=1, max_attempts=3)),
    }


def test_continuation_uses_existing_board_and_director_only():
    director = AstralDirector(mode=DirectorMode.SEMI_AUTO)
    result = dispatch_turn("continuer", board=_board(), director=director, quota=_quota())
    assert result.family is TurnFamily.CONTINUATION
    assert result.owner == "director"
    assert result.proposal.task_id == "TASK-1"
    assert result.proposal.verdict.target_route is RouteKind.RULE
    assert result.proposal.approved is False
    assert result.signature is None
    assert result.escalation is None


def test_new_ask_uses_signature_without_director_proposal():
    director = AstralDirector(mode=DirectorMode.AUTO)
    result = dispatch_turn(
        "extract the columns",
        board=_board(),
        director=director,
        quota=_quota(),
        **_signature_inputs(),
    )
    assert result.family is TurnFamily.ASK
    assert result.owner == "parcimonia"
    assert result.signature.kind == "extract"
    assert result.escalation.state is EscalationState.ACCEPT
    assert result.proposal is None
    assert director.counters.proposed == 0


def test_short_ambiguous_text_neither_resumes_nor_invents_an_ask():
    director = AstralDirector(mode=DirectorMode.AUTO)
    result = dispatch_turn(
        "les maps ?",
        board=_board(),
        director=director,
        quota=_quota(),
        **_signature_inputs(),
    )
    assert result.family is TurnFamily.UNRESOLVED
    assert result.reason_code == "ambiguous_short_text"
    assert result.proposal is result.signature is result.escalation is None
    assert director.counters.proposed == 0


def test_missing_state_or_signature_contract_fails_closed():
    missing_board = dispatch_turn("continuer", director=AstralDirector(), quota=_quota())
    assert missing_board.reason_code == "missing_director_state"
    missing_signature = dispatch_turn("extract the columns")
    assert missing_signature.reason_code == "missing_signature_contract"
