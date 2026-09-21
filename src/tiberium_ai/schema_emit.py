"""Schema-constrained tool emission with act / confirm / refuse bands.

Original adapter inspired by tiny on-device tool-calling models: a call is
either grammar-valid and grounded, withheld, or refused. Empty function_calls
is a refusal, never a guess. No Needle weights are loaded.

Confidence, when present, is the minimum of a declared head score and a decode
probability. Fine-tuned or unmeasured heads report confidence as None, which
cannot auto-act.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Mapping, Sequence

from .router import is_nonnegative_number

__all__ = [
    "EmitBand",
    "EmitVerdict",
    "ProposedCall",
    "SchemaEmitEngine",
    "ToolParameter",
    "ToolSpec",
]


class EmitBand(str, Enum):
    ACT = "act"
    CONFIRM = "confirm"
    REFUSE = "refuse"


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: str
    required: bool = False
    enum: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    default: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("parameter name must be a nonempty string.")
        if self.type not in ("string", "integer", "number", "boolean"):
            raise ValueError("parameter type must be string, integer, number or boolean.")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: tuple[ToolParameter, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("tool name must be a nonempty string.")
        names = [parameter.name for parameter in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique.")

    def param(self, name: str) -> ToolParameter | None:
        for parameter in self.parameters:
            if parameter.name == name:
                return parameter
        return None


@dataclass(frozen=True)
class ProposedCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    decode_probability: float | None = None
    head_confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("call name must be a nonempty string.")
        for label, value in (
            ("decode_probability", self.decode_probability),
            ("head_confidence", self.head_confidence),
        ):
            if value is not None and (not is_nonnegative_number(value) or value > 1.0):
                raise ValueError(f"{label} must be null or in [0, 1].")

    @property
    def confidence(self) -> float | None:
        parts = [value for value in (self.decode_probability, self.head_confidence) if value is not None]
        if not parts:
            return None
        return min(parts)


@dataclass(frozen=True)
class EmitVerdict:
    band: EmitBand
    function_calls: tuple[dict[str, Any], ...]
    suppressed_calls: tuple[dict[str, Any], ...]
    confidence: float | None
    reasoning: str
    ungrounded_fields: tuple[str, ...] = ()


def _looks_grounded(source: str, value: Any, parameter: ToolParameter) -> bool:
    text = source.casefold()
    if parameter.enum:
        return str(value).casefold() in {item.casefold() for item in parameter.enum} and str(value).casefold() in text
    if parameter.type == "boolean":
        if value is True:
            return any(token in text for token in ("true", "on", "enable", "yes", "dim", "bright"))
        if value is False:
            return any(token in text for token in ("false", "off", "disable", "no", "dark"))
        return False
    if parameter.type in ("integer", "number"):
        return str(value) in source
    rendered = str(value).strip()
    if not rendered:
        return False
    return rendered.casefold() in text


def _grammar_error(value: Any, parameter: ToolParameter) -> str | None:
    if parameter.type == "boolean" and type(value) is not bool:
        return f"{parameter.name} must be a boolean."
    if parameter.type == "integer" and type(value) is not int:
        return f"{parameter.name} must be an integer."
    if parameter.type == "number" and type(value) not in (int, float):
        return f"{parameter.name} must be a number."
    if parameter.type == "string" and not isinstance(value, str):
        return f"{parameter.name} must be a string."
    if parameter.enum is not None and str(value) not in parameter.enum:
        return f"{parameter.name} is not in the declared enum."
    if parameter.minimum is not None and isinstance(value, (int, float)) and value < parameter.minimum:
        return f"{parameter.name} is below minimum."
    if parameter.maximum is not None and isinstance(value, (int, float)) and value > parameter.maximum:
        return f"{parameter.name} is above maximum."
    if isinstance(value, str):
        if parameter.min_length is not None and len(value) < parameter.min_length:
            return f"{parameter.name} is shorter than min_length."
        if parameter.max_length is not None and len(value) > parameter.max_length:
            return f"{parameter.name} is longer than max_length."
        if parameter.pattern is not None and re.fullmatch(parameter.pattern, value) is None:
            return f"{parameter.name} does not match pattern."
    return None


class SchemaEmitEngine:
    def __init__(self, withhold_below: float = 0.1, act_at_or_above: float = 0.7) -> None:
        if not is_nonnegative_number(withhold_below) or withhold_below > 1.0:
            raise ValueError("withhold_below must be in [0, 1].")
        if not is_nonnegative_number(act_at_or_above) or act_at_or_above > 1.0:
            raise ValueError("act_at_or_above must be in [0, 1].")
        if withhold_below > act_at_or_above:
            raise ValueError("withhold_below cannot exceed act_at_or_above.")
        self.withhold_below = withhold_below
        self.act_at_or_above = act_at_or_above

    def emit(
        self,
        source_text: str,
        tools: Sequence[ToolSpec],
        proposed: ProposedCall | None,
    ) -> EmitVerdict:
        if not isinstance(source_text, str):
            raise TypeError("source_text must be a string.")
        by_name = {tool.name: tool for tool in tools}
        if len(by_name) != len(tools):
            raise ValueError("tool names must be unique.")

        if proposed is None:
            return EmitVerdict(
                band=EmitBand.REFUSE,
                function_calls=(),
                suppressed_calls=(),
                confidence=None,
                reasoning="No call was proposed; empty list is a refusal, not a guess.",
            )

        spec = by_name.get(proposed.name)
        if spec is None:
            return EmitVerdict(
                band=EmitBand.REFUSE,
                function_calls=(),
                suppressed_calls=(),
                confidence=proposed.confidence,
                reasoning=f"Unknown tool {proposed.name!r}; call withheld.",
            )

        cleaned: dict[str, Any] = {}
        ungrounded: list[str] = []
        for key, value in proposed.arguments.items():
            parameter = spec.param(key)
            if parameter is None:
                return EmitVerdict(
                    band=EmitBand.REFUSE,
                    function_calls=(),
                    suppressed_calls=(),
                    confidence=proposed.confidence,
                    reasoning=f"Argument {key!r} is not in the schema; invalid values are unrepresentable.",
                )
            error = _grammar_error(value, parameter)
            if error is not None:
                return EmitVerdict(
                    band=EmitBand.REFUSE,
                    function_calls=(),
                    suppressed_calls=(),
                    confidence=proposed.confidence,
                    reasoning=error,
                )
            if not _looks_grounded(source_text, value, parameter):
                if parameter.required:
                    ungrounded.append(f"{spec.name}.{parameter.name}")
                continue
            cleaned[key] = value

        for parameter in spec.parameters:
            if parameter.name in cleaned:
                continue
            if parameter.required and parameter.default is None:
                payload = {"name": spec.name, "arguments": dict(cleaned)}
                return EmitVerdict(
                    band=EmitBand.CONFIRM,
                    function_calls=(),
                    suppressed_calls=(payload,),
                    confidence=proposed.confidence,
                    reasoning=f"Required field {parameter.name!r} has no grounded span; call withheld.",
                    ungrounded_fields=tuple(ungrounded + [f"{spec.name}.{parameter.name}"]),
                )
            if parameter.default is not None and parameter.required:
                cleaned[parameter.name] = parameter.default

        payload = {"name": spec.name, "arguments": cleaned}
        confidence = proposed.confidence
        if ungrounded:
            return EmitVerdict(
                band=EmitBand.CONFIRM,
                function_calls=(),
                suppressed_calls=(payload,),
                confidence=confidence,
                reasoning="One or more fields are ungrounded in the source span.",
                ungrounded_fields=tuple(ungrounded),
            )
        if confidence is None:
            return EmitVerdict(
                band=EmitBand.CONFIRM,
                function_calls=(payload,),
                suppressed_calls=(),
                confidence=None,
                reasoning="Call is well-formed but uncalibrated; confirmation required.",
            )
        if confidence < self.withhold_below:
            return EmitVerdict(
                band=EmitBand.CONFIRM,
                function_calls=(),
                suppressed_calls=(payload,),
                confidence=confidence,
                reasoning=f"Confidence {confidence:.2f} is below the withhold floor {self.withhold_below:.2f}.",
            )
        if confidence >= self.act_at_or_above:
            return EmitVerdict(
                band=EmitBand.ACT,
                function_calls=(payload,),
                suppressed_calls=(),
                confidence=confidence,
                reasoning="Grammar-valid, grounded, and above the act threshold.",
            )
        return EmitVerdict(
            band=EmitBand.CONFIRM,
            function_calls=(payload,),
            suppressed_calls=(),
            confidence=confidence,
            reasoning="Call is well-formed but below the act threshold.",
        )
