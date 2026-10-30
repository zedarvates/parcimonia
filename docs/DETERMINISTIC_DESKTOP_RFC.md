# RFC: deterministic inspection and organization

Status: R&D proposal, 2026-10-30. No new route or desktop command is enabled by
this document. The standalone Parcimonia router remains in shadow mode.

## Intent

Extend the minimum-sufficient-mechanism approach to duplicate discovery,
consistency checks and rule-based organization of records. A small configured language
model may translate ambiguous requests into proposed structured commands. The
deterministic layer validates and executes supported commands, then checks the
result. Complex reasoning remains an escalation path.

## User scope correction — 2026-10-30

Current work covers duplicate discovery, missing-link/consistency checks and
rule-based organization. Desktop behavior and visual customization are roadmap
items only. The user identified the intended project as **Custom Desktop by
kelpie-dev** and will provide its link when its website is available, expected
in **November 2026**. This is an indicative availability window, not an automatic
start date. Do not begin desktop research, adapter design or implementation
before receiving that link and inspecting the actual project.

No other desktop repository is an integration target for this proposal.

## Observed sources

| Repository | Observed revision | Relevant source |
| --- | --- | --- |
| Parcimonia | `83f40ebd715d09add32c45a73c44dc48e88a472a` | `src/tiberium_ai/contracts.py`, `registry.py`, `verification.py`, `docs/REGISTRY.md` |
| Botte Secrète | `6037a26789a9470c78450399d6442c291c094f23` (draft PR148) | `skills/fallow_like/analyzers/duplication.py`, `skills/code_fingerprint/__init__.py`, `scripts/check_docs_links.py`, `skills/docs_steward/`, `skills/asset_quality/memory.py`, `skills/response_cache/` |
| Botte hosted service | `1ff900bb7a2465d1b3ea90f94f7e559ce52a8d34`, service 0.4.0 | Deterministic statistics calculator and advisory task assessment; separate deployment from the Python draft |

Repository state and implementation claims must be revalidated before coding.
Paths are evidence of inspected components, not promises that all proposed
adapters exist.

## Reuse before adding capabilities

| Task family | Existing component and actual scope | Next bounded increment |
| --- | --- | --- |
| Byte-identical files | Asset memory accepts supplied SHA-256 identities; it does not read/hash the files. | A local adapter enumerates explicit roots, groups size then full hashes, and verifies bytes before declaring exact copies. Record stable file identities, hard links and read failures. |
| Repeated code fragments | Fallow's duplication analyzer compares normalized eight-line windows using a truncated MD5. Code fingerprints track normalized source changes. | Reuse these as candidate generators. Preserve literals and language semantics in any stronger normalization. Their current hashes are not proofs of equivalent behavior. |
| Identical or similar images | Asset-quality memory compares supplied quality metrics; it does not compare decoded pixels or compute perceptual hashes. | First compare exact bytes. Then define decoder, orientation and color conventions for equal-pixel comparison. A perceptual hash proposes similar candidates with thresholds; it does not prove identity. |
| Redundant features or skills | Capability registry inventories descriptions and lexical matches. | Compare declared inputs, outputs, effects, owners and tests; use a small model only for unresolved semantic grouping. Preserve overlapping features that serve different contracts. |
| Broken documentation links | `check_docs_links.py` checks inline Markdown local target existence outside fenced blocks. It skips HTTP and standalone anchors. | Extend that checker for heading fragments and reference-style links with explicit parser conventions. Keep remote checks separate and distinguish missing, unauthorized, rate-limited and unavailable. |
| Documentation and checklists | Docs Steward maps components and reads open/checked boxes. | Combine missing targets, component documentation and checklist state in one existing report flow. A checked box records text state, not independent proof of completed work. |
| Repeated requests/results | Exact response cache includes query, model and context; fuzzy overlap is a candidate mechanism. | Reuse only when all relevant inputs, target revision, policy and freshness conditions match. Similar wording is not sufficient evidence for accepting an old result. |

Important regression: the existing code-fingerprint normalization also changes
whitespace inside string literals. Fix or avoid that normalization before using
it as evidence of equality. Case-folding arbitrary code can also change meaning.

## More deterministic task candidates

- Inventory, sort, filter, group and rename records under explicit rules.
- Detect duplicate IDs, command registrations, routes and conflicting settings.
- Find orphan references, missing assets, unresolved imports and incomplete metadata.
- Compare configurations, manifests, versions and dependency constraints.
- Apply formatters, lint rules, schema validation and bounded migrations.
- Extract fields with known parsers; compute counters, budgets and statistics.
- Generate indexes, cross-reference maps, checklists and fixed-format reports.
- Cache exact results with provenance; invalidate them when relevant inputs change.
- Check checklist dependencies and flag inconsistent states or blocked next steps.

When the rule is unspecified (for example, "group by meaning" or "make this
prettier"), first resolve a user preset, explicit criteria or a model proposal.
Deterministic execution does not turn an ambiguous objective into a known rule.

## Evidence levels for duplicate discovery

Use distinct result kinds rather than one "duplicate" flag:

1. `exact_bytes`: current bytes verified equal; hashes are a grouping aid.
2. `equal_decoded_content`: equality under a named decoder/normalization.
3. `normalized_candidate`: lexical/AST normalization or fragment overlap.
4. `similar_candidate`: perceptual, lexical or embedding distance.
5. `semantic_overlap_candidate`: a possible shared purpose requiring contract
   comparison and relevant tests.

Results retain source identity/revision, detector version, comparison method,
scope, exclusions and read failures. Candidate outputs do not silently become
verified equivalence or instructions to delete/merge content. The first pilot
produces reports and previews.

## Reuse the current Parcimonia contracts

Parcimonia already has `Task.kind` and structured `Task.inputs`, a versioned
route registry, versioned verifiers, input hashes and observation records.
Reuse them for inspection and organization tasks. Keep proposed capabilities
separate from enabled manifests until matching handlers and verifiers are
available. Do not extend a closed schema without a versioned adapter contract.

## Current bounded R&D sequence

| Lot | Deliverable | Acceptance |
| --- | --- | --- |
| A: inspect | One combined read-only report using existing code/link/documentation detectors, plus a byte-equality file adapter prototype. | Keep equality levels distinct; preserve failures and intentional copies; no false exact matches on a fixed held-out corpus. |
| B: organize records | Explicit sort/filter/group/tag rules over supplied records, with a proposed-change report. | Same inputs and rules yield the same result; preserve identities and report unmatched or ambiguous records. This does not manipulate desktop widgets or appearance. |
| C: verify and compare | Held-out inspection/organization cases and whole-task measurements through existing verifier/observation contracts. | Compare correct results, false matches, abstentions and cost through accepted output; keep unknown usage null. |

## Roadmap only: Custom Desktop by kelpie-dev

Status: **waiting for the user-provided project link**. Expected website
availability: **November 2026**. No URL or architecture is assumed, and no
automatic start or scheduled lookup is created.

Deferred scope includes desktop post-it controls, note colors and placement,
checklist UI controls, window/card layouts, themes, palettes, font settings and
other visual customization. General data organization and checklist reporting
remain in the current inspection/organization scope.

After the user supplies the link, inspect the actual Custom Desktop project and
its current work before deciding the integration boundaries, supported actions,
state persistence, verification and platform requirements. Design must follow
that project's existing implementation rather than an unrelated desktop app.

This document does not launch jobs, restart apps, install software or activate
routes. The desktop/visual roadmap remains blocked until the explicit dependency
above is satisfied.

## Evaluation and cost claims

Compare the same accepted tasks, inputs/revisions, environment and success
criteria across direct deterministic execution, deterministic plus a small model,
and the current agent baseline. Keep development cases separate from held-out
cases. Include negative and ambiguous French/English requests.

Measure route selection, false exact-duplicate claims, candidate recall/precision,
task success, abstentions, retries, time to accepted result, model call count,
available provider usage, CPU/RAM and verification cost. Retain the entire
workflow cost, including routing, context, tool responses and fallback.

Use the exact model identifier available to the selected runtime. A conversational
nickname does not establish a deployable model ID, pricing or availability.
Subscription quota and API billing are different measurements.

A deterministic step can avoid model calls for its computation, while the agent
that requests or explains it can still consume tokens. Lower cost than another
provider, including DeepSeek, is a benchmark hypothesis until measured at equal
success and verification requirements. Unknown token or price measurements stay
null; no savings percentage is inferred from architecture alone.
