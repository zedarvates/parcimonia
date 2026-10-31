"""Explicit context requirements alongside a legacy task signature, without authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping, Sequence

from .contracts import Verification
from .decision_json import canonical_json
from .task_signature import TaskSignature
from .verification import VerifierRegistry, hash_input

CONTEXT_SCHEMA_VERSION = 2
_VALUE_KINDS = {"str", "number", "bool", "list", "dict"}


def _name(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a nonempty, trimmed string.")


@dataclass(frozen=True)
class ContextField:
    name: str
    description: str
    value_kind: str = "str"

    def __post_init__(self) -> None:
        _name(self.name, "field name")
        _name(self.description, "field description")
        if self.value_kind not in _VALUE_KINDS:
            raise ValueError("unsupported context value kind.")

    def accepts(self, value: Any) -> bool:
        if self.value_kind == "str":
            return isinstance(value, str) and bool(value.strip())
        if self.value_kind == "number":
            return type(value) in (int, float) and (isinstance(value, int) or math.isfinite(value))
        if self.value_kind == "bool":
            return type(value) is bool
        if self.value_kind == "list":
            return isinstance(value, list) and bool(value)
        return isinstance(value, Mapping) and bool(value)


@dataclass(frozen=True)
class ContextContract:
    """Host-declared requirements for one operation, not inferred from keywords."""
    contract_id: str
    version: str
    task_kind: str
    fields: tuple[ContextField, ...]
    required_context: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("contract_id", "version", "task_kind"):
            _name(getattr(self, name), name)
        if isinstance(self.fields, (str, bytes)) or not isinstance(self.fields, Sequence):
            raise TypeError("fields must be a sequence.")
        fields = tuple(self.fields)
        if not fields or not all(isinstance(f, ContextField) for f in fields):
            raise ValueError("fields must contain ContextField declarations.")
        names = [f.name for f in fields]
        if len(set(names)) != len(names):
            raise ValueError("context field names must be unique.")
        if isinstance(self.required_context, (str, bytes)) or not isinstance(self.required_context, Sequence):
            raise TypeError("required_context must be a sequence.")
        required = tuple(self.required_context)
        if any(not isinstance(name, str) or name not in names for name in required):
            raise ValueError("required_context must use declared field names.")
        if len(set(required)) != len(required):
            raise ValueError("required_context must not repeat a field.")
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "required_context", required)

    def to_record(self) -> dict[str, Any]:
        return {"schema_version": CONTEXT_SCHEMA_VERSION, "contract_id": self.contract_id,
                "version": self.version, "task_kind": self.task_kind,
                "fields": [asdict(f) for f in self.fields], "required_context": list(self.required_context)}

    def fingerprint(self) -> str:
        return hash_input(self.to_record())


def reference_payload(contract: ContextContract, *, field: str, reference_id: str,
                      context_revision: str) -> dict[str, Any]:
    """The exact descriptor a host's named availability verifier must check."""
    if field not in {f.name for f in contract.fields}:
        raise ValueError("reference field is undeclared.")
    _name(reference_id, "reference_id")
    _name(context_revision, "context_revision")
    return {"schema_version": CONTEXT_SCHEMA_VERSION, "contract_hash": contract.fingerprint(),
            "field": field, "reference_id": reference_id, "context_revision": context_revision}


@dataclass(frozen=True)
class ContextAssessment:
    contract_hash: str
    input_hash: str
    context_revision: str
    context_complete: bool
    provided_fields: tuple[str, ...]
    referenced_fields: tuple[str, ...]
    available_context: tuple[str, ...]
    required_context: tuple[str, ...]
    missing_context: tuple[str, ...]
    unknown_context: tuple[str, ...]
    invalid_fields: tuple[str, ...]
    field_status: Mapping[str, str]
    reference_verification: Mapping[str, Mapping[str, Any]]
    status: str

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_record(self) -> dict[str, Any]:
        record = {**asdict(self), "schema_version": CONTEXT_SCHEMA_VERSION,
                  "ready": self.ready, "auto_act_allowed": False}
        for name in ("provided_fields", "referenced_fields", "available_context", "required_context",
                     "missing_context", "unknown_context", "invalid_fields"):
            record[name] = list(record[name])
        return record


def assess_context(
    contract: ContextContract, *, context_revision: str,
    values: Mapping[str, Any] | None = None, references: Mapping[str, str] | None = None,
    reference_evidence: Mapping[str, Verification] | None = None,
    verifiers: VerifierRegistry | None = None, context_complete: bool = False,
) -> ContextAssessment:
    """Assess declared inputs and host evidence; never read files or call verifiers.

    Absence is missing only for a host-declared complete snapshot. Otherwise
    it is unknown. A verified reference supplies availability, not an inline value.
    """
    if not isinstance(contract, ContextContract):
        raise TypeError("contract must be a ContextContract.")
    _name(context_revision, "context_revision")
    if type(context_complete) is not bool:
        raise TypeError("context_complete must be a boolean.")
    if verifiers is not None and not isinstance(verifiers, VerifierRegistry):
        raise TypeError("verifiers must be a VerifierRegistry or null.")
    inputs = []
    for label, value in (("values", values), ("references", references), ("reference_evidence", reference_evidence)):
        if value is not None and not isinstance(value, Mapping):
            raise TypeError(f"{label} must be a mapping or null.")
        inputs.append(dict(value) if value is not None else {})
    values, references, evidence = inputs
    names = tuple(f.name for f in contract.fields)
    if any(set(items) - set(names) for items in inputs):
        raise ValueError("context contains undeclared fields.")
    if set(values) & set(references):
        raise ValueError("a context field cannot be both inline and referenced.")
    if set(evidence) - set(references):
        raise ValueError("reference evidence has no matching reference.")
    if any(not isinstance(proof, Verification) for proof in evidence.values()):
        raise TypeError("reference evidence must contain Verification records.")
    for field, reference_id in references.items():
        reference_payload(contract, field=field, reference_id=reference_id, context_revision=context_revision)
    # Validate JSON before hashing; never coerce field names or non-finite values.
    canonical_json(values)
    payload = {"contract_hash": contract.fingerprint(), "context_revision": context_revision,
               "context_complete": context_complete, "values": values, "references": references,
               "reference_evidence": {name: proof.to_record() for name, proof in evidence.items()}}
    statuses = {}
    for spec in contract.fields:
        name = spec.name
        if name in values:
            statuses[name] = "available_inline" if spec.accepts(values[name]) else "invalid_value"
        elif name in references:
            proof = evidence.get(name)
            expected = reference_payload(contract, field=name, reference_id=references[name], context_revision=context_revision)
            if proof is None or verifiers is None or not verifiers.is_registered(proof.verifier_id, proof.verifier_version):
                statuses[name] = "unverified_reference"
            elif proof.input_hash != hash_input(expected):
                statuses[name] = "reference_input_mismatch"
            elif proof.verdict is True:
                statuses[name] = "available_reference"
            elif proof.verdict is False:
                statuses[name] = "unavailable_reference"
            else:
                statuses[name] = "reference_unknown"
        else:
            statuses[name] = "absent" if context_complete else "unobserved"
    available = tuple(name for name in names if statuses[name] in {"available_inline", "available_reference"})
    missing = tuple(name for name in contract.required_context if statuses[name] in {"absent", "invalid_value", "unavailable_reference"})
    unknown = tuple(name for name in contract.required_context if name not in available and name not in missing)
    invalid = tuple(name for name in names if statuses[name] == "invalid_value")
    status = "invalid_context" if invalid else "missing_context" if missing else "context_unknown" if unknown else "ready"
    return ContextAssessment(contract.fingerprint(), hash_input(payload), context_revision, context_complete,
        tuple(name for name in names if name in values), tuple(name for name in names if name in references),
        available, contract.required_context, missing, unknown, invalid, statuses,
        {name: proof.to_record() for name, proof in evidence.items()}, status)


@dataclass(frozen=True)
class SignatureContext:
    """Versioned companion to a v1 signature; legacy fields are never relabelled."""
    signature: TaskSignature
    context: ContextAssessment
    status: str

    def to_record(self) -> dict[str, Any]:
        return {"schema_version": CONTEXT_SCHEMA_VERSION, "kind": "signature_context",
                "signature": self.signature.to_record(), "context": self.context.to_record(),
                "status": self.status, "ready": self.status == "ready", "auto_act_allowed": False}


def enrich_signature_context(signature: TaskSignature, prompt: str, contract: ContextContract,
                             **context_inputs: Any) -> SignatureContext:
    if not isinstance(signature, TaskSignature):
        raise TypeError("signature must be a TaskSignature.")
    if not isinstance(prompt, str) or signature.prompt_hash != hash_input(prompt):
        raise ValueError("signature does not match this prompt.")
    context = assess_context(contract, **context_inputs)
    status = ("signature_abstained" if signature.abstained else
              "kind_contract_mismatch" if signature.kind != contract.task_kind else context.status)
    return SignatureContext(signature, context, status)
