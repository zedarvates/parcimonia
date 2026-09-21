# Static audit: a System-1 route with a local memory

The static audit answers one question without calling a model: does this file
declare more than it implements? It is the cheapest route Parcimonia can offer
for that question, and it exists as a route rather than as a linter because the
point is the routing contract, not the diagnostics.

```text
source text
    |
    +-- scan      structure only: lines, bodies, decision points, imports
    +-- classify  what this file is: module, package marker, interface, script, ...
    +-- check     named pattern rules, filtered by role
    +-- score     four ratio dimensions + capped rule penalty -> deficit and band
    +-- store     content-addressed verdict cache, keyed by policy version
    +-- verify    recompute the verdict before accepting it as evidence
```

Nothing in that chain imports the audited module, executes it, reads a clock,
touches the network or calls a model. The same bytes and the same policy version
always produce the same verdict, which is what makes the cached verdict safe to
reuse.

## Structural roles come first

`source_role.py` decides what a file *is* before anything is judged, because one
rule set produces systematic false positives across different kinds of file. An
interface whose bodies are `...` has no logic by construction; a re-export module
consumes no name locally; a docstring-only package marker is a packaging
convention. Each role names the checks it suppresses, and the classifier returns
the reason code that produced it.

| Role | Detected by | Suppresses |
| --- | --- | --- |
| `package_init` | file named `__init__.py` | `documentation_balance`, `import_hygiene` |
| `re_export` | no function and no class, at least 70% imports and assignments | `import_hygiene` |
| `interface` | every top-level class inherits `Protocol`, `ABC` or `ABCMeta`, no function | `substance` |
| `script` | a top-level `if __name__ == "__main__":` guard | none |
| `test` | path under `tests/`, or `test_*.py`, or `*_test.py` | none |
| `generated` | a generation marker in the first eight lines | everything |
| `corpus` | a path component `corpus` or `fixtures` | everything |
| `module` | none of the above | none |

Detection order is fixed and short-circuits, so a file only ever lands in one
role. A suppression name that matches no dimension and no wildcard is refused at
audit time: a misspelled exemption would otherwise silently stop exempting
anything.

Suppression is not the same as abstention. A role that suppresses every check
produces an `undetermined` verdict with the reason code
`role_suppresses_all_checks`, never a clean one. Text that cannot be parsed
produces `undetermined` with `source_unparsable` and keeps no suppression at all.

## Four ratio dimensions

Every dimension is a ratio in `[0, 1]` where 1 is best. The measurement that
produced the number travels with it, so a report can be argued with.

| Dimension | Weight | Measured as |
| --- | --- | --- |
| `substance` | 0.35 | function bodies that do more than declare themselves |
| `structure_integrity` | 0.25 | functions at or below 12 decision points |
| `documentation_balance` | 0.20 | code lines against comment plus docstring lines |
| `import_hygiene` | 0.20 | imported names consumed or re-exported |

A body counts as filled when it contains at least one statement that is not
`pass`, a bare string, `...` or a `NotImplementedError` raise: those four are
declarations of intent. Comments are counted with `tokenize`, so a `#` inside a
string is not a comment. A star import and a `__future__` import are always
counted as consumed, and a quoted forward reference such as
`registry: "RouteRegistry | None"` counts as a use, because `undecidable` is not
the same claim as `unused`.

Values outside `[0, 1]` are clamped and reported in `clamped` rather than
rejected: a measurement bug has to be visible instead of quietly distorting a
score.


## Deficit, band and attribution

The four dimensions are combined with a **weighted geometric mean**, not a
weighted sum: one collapsed dimension cannot be averaged away by three healthy
ones. The base deficit is `100 * (1 - gqg)`. Discrete rule findings then add a
penalty of 12 for a `blocker`, 6 for `high`, 2.5 for `medium` and 1 for `low`,
capped at 40 so a single repeated defect cannot carry the whole verdict.

| Deficit | Band |
| --- | --- |
| under 20 | `sound` |
| 20 or more | `noted` |
| 40 or more | `questionable` |
| 60 or more | `inflated` |
| 80 or more | `critical` |

A `blocker` raises the band floor to `questionable`, and three or more `high`
findings raise a `sound` file to `noted`. The deficit is then attributed back to
its sources by log-loss share, with the rule share kept separate, so the number
a caller acts on always names where it came from.


## Named pattern rules

| Rule | Axis | Severity | Applies to |
| --- | --- | --- | --- |
| `rule.placeholder-marker` | placeholder | medium | module, package marker, interface |
| `rule.silent-except` | structure | high | module, package marker, interface, test |
| `rule.debug-emit` | hygiene | low | module, package marker |
| `rule.inflated-claim` | claim | medium | module, package marker, re-export, interface |

`rule.placeholder-marker` reads comments only. A docstring describes behaviour,
and a sentence such as "two-stage scoring is not implemented" is accurate prose
about a deliberate limitation; restricting the rule to comments removes that
class of false positive. Markers are matched on word boundaries, so the
exception class name `NotImplementedError` is not read as the two-word
deferred-work marker.

`rule.silent-except` reports a bare handler once, and reports a handler whose
whole body is `pass` or a bare string separately. Deliberate control flow such as
`continue`, `break` or `return` is left alone.

`rule.debug-emit` does not apply to test modules, scripts or generated code: a
program's own stdout is its interface, not leftover debris.

`rule.inflated-claim` is an explicit lexicon, not a judgement about meaning. It
is the least trustworthy rule in the set and is expected to be tuned against
labelled examples before any threshold built on it is used to decide anything.

Every rule caps at five findings per file. The cap bounds what one repeated
defect can contribute and keeps a report readable.


## The local verdict store

The store is a SQLite file whose key is `(content hash, policy version)`. The
content hash covers the path as well as the text, because role classification
depends on the path, so the same bytes at two paths are two different audits.

A stored record keeps the timestamp, project label, policy version, content hash,
role, reason code, band, deficit, the four dimension ratios, the rules that fired
with their counts, and the attribution. The source text is **not** stored, and
neither is the path: a leaked database leaks ratios, not a repository.

Three rules keep reuse honest:

* a second record with the same key and a different verdict is refused as a
  determinism failure instead of overwriting the first, so non-determinism is
  surfaced where it happens
* only records whose provenance is `measured` and whose band is determined are
  offered for reuse: fixture and synthetic verdicts are observability, and an
  abstention is not a cached answer
* the store never reads a clock, so `recorded_at` comes from the caller and
  recording is reproducible; `export_jsonl` refuses to overwrite a file

The table is stamped with a schema version in `PRAGMA user_version`. A file this
build does not understand is refused rather than migrated blind, and the store
never creates its own parent directory.


## Policy version pins the rules

`audit_policy_version(base)` returns `base + "+rules:" + fingerprint`, where the
fingerprint hashes the enabled rule ids, axes, severities, role applicability and
the findings cap. `audit_source` refuses a policy version that does not end with
the fingerprint of the rule set it is about to run: a verdict cannot be
attributed to rules that did not produce it, which is what stops a stale cache
entry from being reused after a rule edit.

Disabling one rule therefore produces a new policy version, a new store key and a
new audit. That is the intended cost of the guarantee.

## Verification is recomputation

`register_audit_verifiers` binds `audit.recompute` version `1` to a verifier that
recomputes the audit from the source and compares the content hash, the band and
the deficit with the claim. A mismatch is a rejection. A payload that is not
shaped correctly raises, which the verifier registry records as an abstention
rather than a pass. A source that turns out to be unauditable is rejected: an
abstention never verifies as accepted evidence.

`audit_route_entry(...)` builds the manifest entry for this route and has no
default for `estimated_cost`. A route's cost is a measurement or a declared
estimate, never a number invented by an assembly function; `confidence` stays
`null` until it has been calibrated.


## Running it

```powershell
python examples/audit_suite.py --out runs/audit --root src/tiberium_ai
```

The suite audits every file, records each verdict in a local store, audits the
tree a second time to show the store answering instead of the analyser, verifies
each determined verdict by recomputation, and writes `summary.json` plus a
`records.jsonl` export. It refuses to overwrite an existing output directory.
Vendored, cached and build trees are skipped, so widening the root does not widen
what counts as authored code.

On this repository, `--root src/tiberium_ai` reports 33 files, all `sound`, a mean
deficit around 5.4, no rule findings, 33 reused verdicts on the second pass and
33 accepted verifications. `--root .` reports 68 authored files with 873 vendored
files skipped, a mean deficit around 3.2 and still no rule findings. Those
numbers describe a local audit; no model was called, so there is no baseline and
no saving claim.

## What this is not

* not a model, and not a substitute for review: it measures structure, and a
  well-structured file can still be wrong
* not calibrated: the weights, the thresholds and the claim lexicon are declared
  defaults, not tuned values, so no threshold here may gate execution yet
* not a lint runner and not a dependency of the router: the route is registered
  as a candidate, and the shadow router still chooses nothing on its own
* not architecture-aware: it has no notion of a layer, a contract or a design
  intent, so it cannot tell a deliberate seam from an accident

## Next gate

Calibration comes before any threshold is trusted. The work is to label a set of
files, measure per-rule false positives on that set, and publish the resulting
weights and thresholds as a recorded snapshot with `data_origin` set honestly.
Until that snapshot exists, the deficit is a reported measurement and nothing
more. A model-backed route over the same question is the natural baseline for
the cost comparison, and it cannot be claimed before that baseline has been run
on the same tasks.
