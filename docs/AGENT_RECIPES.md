# Agent recipes: bounded decisions for developer workflows

Implemented from the two Jev video analyses on 2026-10-02. This package adds
usable local workflows and a JSON interface, without changing production routing
or installing hooks in an existing agent. Import from `tiberium_ai.agent_recipes`.

## Run the offline walkthrough

From the repository root, using the existing development environment:

```powershell
rtk .\.venv\Scripts\python.exe examples/agent_recipes_suite.py --out runs/agent-recipes.json
```

The output is exclusively created; a second run must choose another filename.
Nine recipe results exercise the integration with injected fixture judgments.
The index and usage journal are real local SQLite operations. The measured
pipeline executes real local callables; its judgments remain authored fixtures.
Neither this walkthrough nor passing tests establish semantic accuracy, live
browser behavior, paid-provider performance or savings.

## Skill catalog and journal

`SkillCatalog.sync(root, at=...)` scans SKILL.md files below one explicit root,
rejects escaped paths and oversized input, computes content fingerprints and
preserves usage history across edits. Unchanged entries retain their indexing
timestamp. Removed files become absent without deleting their historical events.
The complete scan is prepared before a database transaction, so failed reads do
not silently remove skills. Files are read to detect content changes; this is not
an OS file watcher. Multiple skill roots can share a database.

Names and descriptions support simple Markdown front matter, including block
descriptions. Full YAML semantics are not implemented. The agent must still read
the selected SKILL.md instructions. Callers supply eligible IDs after applying
environment and authorization constraints. An explicit skill choice takes
precedence over model selection and cannot bypass eligibility.

`record_use(skill_id, event_id=..., at=..., outcome=...)` records actual host
events. Timezones are required and normalized to UTC. A repeated identical event
is idempotent; reusing its ID with different content fails. The journal does not
invent a creation date or usage that occurred before collection began.

Example CLI input file `index.json`:

```json
{"root":"C:/Users/redga/.agents/skills"}
```

```powershell
rtk .\.venv\Scripts\python.exe -m tiberium_ai.agent_recipes index --input index.json --db runs/skills.sqlite
rtk .\.venv\Scripts\python.exe -m tiberium_ai.agent_recipes skill --input query.json --db runs/skills.sqlite
```

`query.json` contains `{"query":"debug Python errors"}` and may add
`eligible_ids` and `explicit_id`. Without a decision backend, an ambiguous skill
request abstains and returns candidates for the host's normal selection.

## Recipes and host boundary

| CLI command | Input | Behavior |
| --- | --- | --- |
| `index` | root, optional at; --db | incremental metadata indexing |
| `usage` | skill_id, event_id, at, outcome; --db | actual usage event |
| `audit-skills` | {}; --db, optional --csv | usage/duplicate report, no deletion |
| `skill` | query, optional eligible_ids/explicit_id; --db | eligible shortlist then choice or none |
| `rank` | query and files, or query and root | lexical candidates then batched semantic ranking |
| `compact` | query, blocks, optional target_chars | verbatim retained blocks and reversible recall |
| `review` | changes, optional rules | review-depth proposal; effective review remains full |
| `rules` | change and rules | pattern/syntax checks and semantic review signals |
| `requirements` | requirements and tests | requirement/test links with relevance signals |
| `feedback` | records | sentiment and help/bug signals; deterministic totals |
| `browser` | goal and snapshot | dry next-action proposal, never executes a browser |
| `compare` | baseline and candidate | paired pipeline report; no certified savings claim |

Files can be supplied by an existing rg search as objects with `id`, `excerpt`
and `content_hash`. The lexical fallback bounds file count and byte size and
excludes .git, virtual environments, dependencies and runs. A weak result calls
for wider search; it never proves no relevant file exists. A host must recheck
fingerprints before consuming a candidate. Skills must be shortlisted to at most
19; this preserves room for `none` under the existing Reflex choice cap.

Context blocks have `id`, `text`, `kind`, and optionally `protected`. Goal,
instruction, authorization, decision, pending, error and evidence blocks are
mandatory. Unknown backend or uncertain relevance keeps the block. Removed
blocks are included in the recall map with their original text, complete block
and hash. Persist this output locally before replacing context; no transcript
is automatically edited. The target is measured in characters, not tokens.

Rules have `id`, `kind`, optional `glob` and either `pattern` (`forbid_regex`) or
`instructions` (`semantic`). Python syntax is checked with AST parsing. Regex
rules are trusted project policy, not untrusted user input. Unknown rule types
and uncertain or positive semantic signals request review. With
`--enforce-rules`, the CLI exits 10 for deterministic block, 11 for required
review, 0 for pass and 2 for malformed input. The host must prevent the edit on
10/11/2. A semantic negative is not independent authorization for an edit.

Requirements have `id`, `text`. Tests have `id`, `requirement_ids`, `source`,
`result` and optional `execution_ref`. The caller supplies actual test source
and execution evidence. This recipe does not execute tests or certify coverage;
even a linked passing test may have irrelevant assertions.

`BrowserRunner.run` accepts observation, executor, approval and goal-verifier
callbacks. It selects only controls from a snapshot, checks freshness, limits
steps and detects unchanged-state loops. No approval callback means no action.
The executor must compare the supplied version atomically before acting. A
model's `done` answer cannot replace the host's goal verifier. This is a host
integration interface, not an installed Playwright/Codex/Hermes driver. Role
access must also be checked with independent direct-access tests.

## Backend, cache and limits

`DecisionSession` uses the existing Reflex engine for answer validation. It
records complete request identities, raw normalized answers, elapsed time,
backend/model identity and reported token usage. Failed attempts count against
the call budget. State size and deadlines are bounded. An answer arriving after
the deadline is discarded. Backend timeouts bound individual network operations;
the session cannot forcibly cancel an arbitrary blocking injected callable.

All semantic proposals set `auto_act_allowed=false`. Confidence from a provider
is not measured calibration on these task families. The pilot's next gate is a
held-out outcome corpus, especially for French prompts and rare failures.

`TypeSafeBackend` implements the official HTTP endpoint, with pinned model
identity, network opt-in, call cap, finite timeout and no implicit retries. It
normalizes Noul probabilities and Score index keys into the existing Reflex
contract. Construction never calls the network. CLI real calls require both
`--allow-network --model <pinned-version>` and `TYPESAFE_API_KEY`. They send the
supplied input to TypeSafe and may be billed; **none were made during validation**.
OpenRouter and Vercel gateways are not implemented by this direct transport.
No local decision-model weights are downloaded, loaded or trained.

`--answers answers.json` supplies recorded normalized Reflex answers offline.
`--cache runs/decisions.sqlite` caches schema-validated responses by exact state,
questions and backend identity. New content or a different version invalidates
reuse. Only choose caching for questions fully described by state: time-sensitive
conditions must be explicit inputs. Cache hits have zero new provider tokens;
that does not mean zero CPU/storage cost. Billed cost is unknown when the
provider reports only token counts. The cache and traces are local and may
contain private data; keep them in ignored runs/, never the public corpus.

## Registry and evidence

`integration.recipe_manifest()` supplies nine routes with unknown cost and
confidence, and `register_recipe_verifier(registry)` registers
`agent.recipe.structure@1`. The verifier binds input state and proposal and
recomputes context partition/recall, feedback totals and eligible selections.
It proves structural properties, never semantic truth or authorization. Existing
shadow routing abstains on these uncalibrated estimates; production registration
and automatic activation are separate decisions.

`measure_pipeline` records ordered callable phases such as collect, prepare,
decide, execute and synthesize, plus the verifier's elapsed time. Phase costs and
tokens must come from measurements or receipts. Missing costs remain unknown.
Human correction and verification costs must be reported separately if not
included as phases. `compare_pipelines` refuses mismatched cases, input hashes,
currency, failed verification or unknown costs. Its result never certifies a
saving; use the existing canonical benchmark chain for that gate.

## Sources

The additional attention and novelty recipes, bounded local source search and
recoverable fixture pilot are documented in [Source triage](SOURCE_TRIAGE_PILOT.md).
Their structural verifier is separately versioned; the nine-route manifest above
retains its existing contract.

- https://www.youtube.com/watch?v=2nc_QMuNp18
- https://www.youtube.com/watch?v=87-OXPkXLJ4
- https://docs.typesafe.ai/api (HTTP contract checked 2026-10-02)

Implementation is original Parcimonia code; no external plugin code or weights
were copied. No host configuration, credentials, service or concurrent files
were modified.
