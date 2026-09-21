import pytest

from tiberium_ai.schema_emit import (
    EmitBand,
    ProposedCall,
    SchemaEmitEngine,
    ToolParameter,
    ToolSpec,
)


LIGHTS = ToolSpec(
    name="set_lights",
    description="Turn a room's lights on or off.",
    parameters=(
        ToolParameter("room", "string", required=True),
        ToolParameter("on", "boolean", required=True),
        ToolParameter("brightness", "integer", required=False, minimum=0, maximum=100),
    ),
)


def test_empty_proposal_is_refusal_not_guess():
    verdict = SchemaEmitEngine().emit("dim the living room", [LIGHTS], None)
    assert verdict.band == EmitBand.REFUSE
    assert verdict.function_calls == ()
    assert "not a guess" in verdict.reasoning


def test_act_band_when_grounded_and_confident():
    proposed = ProposedCall(
        name="set_lights",
        arguments={"room": "living room", "on": True, "brightness": 30},
        decode_probability=0.92,
        head_confidence=0.88,
    )
    verdict = SchemaEmitEngine().emit("dim the living room lights to 30", [LIGHTS], proposed)
    assert proposed.confidence == 0.88
    assert verdict.band == EmitBand.ACT
    assert verdict.function_calls[0]["arguments"]["brightness"] == 30


def test_invalid_value_is_unrepresentable():
    proposed = ProposedCall(
        name="set_lights",
        arguments={"room": "living room", "on": True, "brightness": 400},
        head_confidence=0.99,
    )
    verdict = SchemaEmitEngine().emit("set living room brightness 400", [LIGHTS], proposed)
    assert verdict.band == EmitBand.REFUSE
    assert verdict.function_calls == ()


def test_missing_required_is_withheld():
    proposed = ProposedCall(
        name="set_lights",
        arguments={"on": True},
        head_confidence=0.95,
        decode_probability=0.95,
    )
    verdict = SchemaEmitEngine().emit("turn the lights on", [LIGHTS], proposed)
    assert verdict.function_calls == ()
    assert verdict.suppressed_calls
    assert verdict.band == EmitBand.CONFIRM


def test_ungrounded_optional_is_omitted_required_is_held():
    proposed = ProposedCall(
        name="set_lights",
        arguments={"room": "living room", "on": True, "brightness": 30},
        head_confidence=0.9,
        decode_probability=0.9,
    )
    verdict = SchemaEmitEngine().emit("turn on the living room lights", [LIGHTS], proposed)
    assert verdict.ungrounded_fields == ()
    assert verdict.band == EmitBand.ACT
    assert "brightness" not in verdict.function_calls[0]["arguments"]


def test_uncalibrated_call_cannot_act():
    proposed = ProposedCall(
        name="set_lights",
        arguments={"room": "kitchen", "on": False},
    )
    verdict = SchemaEmitEngine().emit("turn off the kitchen lights", [LIGHTS], proposed)
    assert proposed.confidence is None
    assert verdict.band == EmitBand.CONFIRM
    assert verdict.function_calls


def test_low_confidence_is_withheld():
    proposed = ProposedCall(
        name="set_lights",
        arguments={"room": "kitchen", "on": True},
        head_confidence=0.05,
        decode_probability=0.99,
    )
    verdict = SchemaEmitEngine().emit("turn on the kitchen lights", [LIGHTS], proposed)
    assert proposed.confidence == 0.05
    assert verdict.function_calls == ()
    assert verdict.suppressed_calls
