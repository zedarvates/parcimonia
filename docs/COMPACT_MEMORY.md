# Bounded context and temporal persistence

This opt-in experiment keeps bounded working references, retrieves exact facts
from a caller-owned versioned source, and optionally holds an observation-only
route proposal through marginal estimate changes. It uses the existing
`VerifierRegistry`, `ShadowRouter` and benchmark harness. No runtime dependency
or transport is added.

## Exact facts before a proposal

`CompactMemory.context(entity_id, source_version, required_keys)` requests every
required key from the injected source. A source returns a `MemoryFact` naming its
entity, key, immutable version and named/versioned verifier. Retrieval runs that
verifier every time, binds the verdict to the exact JSON payload hash and returns
only accepted values. Scope/version mismatches, missing sources, unknown or
rejecting verifiers and source failures become explicit `missing` entries.
An incomplete context makes `ContextShadowRouter` abstain.

Working state stores references and verifier identities, never fact values or
conversation history. Defaults retain at most 8 entities and 16 references per
entity; identifiers have a 128-byte limit. A fact payload is limited to 4096
UTF-8 bytes and a context record to 8192. Entity and reference eviction use LRU.
The context budget excludes the caller's task envelope and external archive;
the example reports both separately. An oversized context raises `ValueError`
without committing state; the caller must reduce the request or abstain, rather
than silently truncate constraints.

A changed fact or verifier identity under the same source version is rejected
while the old reference is retained. A new source version clears that entity's
old references. Eviction forgets local pins: the external source must enforce
immutable snapshots independently. A bounded working state does not bound the
external archive and does not preserve unlimited history.

`checkpoint()` exports only bounded references, a schema, limits and a content
hash. `restore()` validates shape, budgets, identities and hash before atomically
replacing state. It does not load trusted facts: every subsequent retrieval
rechecks the source and verifier. Hashes detect inconsistency, not malicious
replacement; verifier registration and source trust remain caller-owned. Obtain
fresh contexts from `CompactMemory`, rather than importing exported context JSON
as authenticated input. Nested values returned by `to_record()` are detached.

## Persistence has an exit

Tasks passed to `ContextShadowRouter.propose()` must bind `inputs.entity_id` and
`inputs.source_version` to their context. The router preserves normal confidence,
cost validity and task-requirement abstentions, and checks required capabilities
even for explicit candidates. It returns only `Decision(mode="shadow")`.

Persistence applies only while the full task inputs, context, tool epoch, policy,
capability families and known failure modes are unchanged. Both routes must
remain eligible and have known estimates in the same unit/basis. A caller may
opt into a relative estimated-cost margin between 0 and 10%; the default is 0.
The authored example uses 2%, with at most 3 consecutive holds. A hold may accept
a small declared cost disadvantage; it does not prove better quality or saving.
Declared confidence remains uncalibrated.

A missing fact, critical-change flag, substantial estimated-cost reduction,
unknown cost or changed task/source/tool/capability state defeats persistence.
Routes in different capability families are never held against each other. The
caller owns `routing_epoch` and must change it when tools, models, routing
semantics or the applicable estimation basis change. Route state is bounded
separately by `max_entities`, and resets on process restart; only working
references have a checkpoint. Nothing executes or promotes a proposal.

## Reproduce the authored A/B/C comparison

From an installed checkout, or with `PYTHONPATH=src`:

```bash
python examples/compact_memory_suite.py --out runs/compact-memory
python -m pytest -q
```

| Variant | Prepared context | Proposal |
| --- | --- | --- |
| `full_history` | Task, full authored history and current exact lookup | Stateless `ShadowRouter` |
| `compact` | Task and requested verified facts | Stateless `ShadowRouter` |
| `compact_persistent` | Same compact context | `ContextShadowRouter` |

All variants share the same indexed external archive, exact verifier and declared
synthetic route estimates; all required facts are retrieved again on each step.
The baseline has an independent stateless retrieval implementation. It omits
per-fact proof metadata from its prepared history, so compact context can be
larger for a short history. Source snapshots are preloaded fictional fixtures;
they do not test a live ingestion pipeline or source access latency.

Fourteen authored sequences cover short/long history, estimate jitter, homonyms,
version/task/tool changes, missing/rejected/unattributed facts, restart, critical
changes and a cheaper deterministic route. An independent exact oracle verifies
fact values, abstentions and required immediate switches. A seed fixes the
development/held-out split, but every authored case is public; this is not an
independent private usage sample or a measured answer-quality benchmark.

The existing harness writes 42 wall-clock measurements and 14 observations.
`context-summary.json` adds all authored traces, their named/versioned verifier
records, exact input hashes, fixture/code fingerprints and deterministic context
metrics. `report.json` records local Python timing and explicitly limits its
claim scope. The harness may allow a single-pass local timing comparison; that
does not grant a production saving claim. The example always refuses such a
claim without a model/real-usage measurement. Output records are not overwritten.

UTF-8 JSON bytes are measured from prepared payloads. They are **not tokens**,
model calls or provider usage. Cost, tokens, VRAM and energy remain unknown. CPU
timing includes source construction, retrieval, verification, context preparation
and proposals; it is one local pass with no model inference. Archive bytes and
reference bytes are serialized sizes, not process RAM. Raw outputs stay in the
git-ignored `runs/` directory. The dated wiki record keeps authored evidence and
negative results: [3 October 2026](../wiki/COMPACT_MEMORY_2026-10-03.json).

## Source and scope

The SwiLA paper, [Switching Linear Attention](https://arxiv.org/html/2609.39034v1),
motivated the analogy of bounded state and temporal persistence. This application
code implements no attention kernel, trained recurrent memory or SwiLA model.
The [official repository](https://github.com/lindermanlab/switching-linear-attention)
contained a README/license and no implementation at revision
`6ce166c0781ac9a332f90e88ec6de8fd68c5deb6` when inspected on 3 October 2026.

The shared video [D6UKzes3zag](https://youtu.be/D6UKzes3zag) was identified by its
metadata and description. No transcript, audio or frames were inspected; the
technical analysis relied on the primary paper and repository. No source code
or model was copied. Botte Secrète's separate RSI observer can later consume
these proofs after a versioned real-trace adapter is available. This experiment
does not change that observer, Needle calibration or Nomad's single-shard scope.
