# Offline replay of versioned memory sequences

`memory_replay.py` accepts explicit local files and builds normal `BenchmarkCase`
objects for the existing harness. It compares full history, compact context and
compact context with bounded shadow persistence. It reads no chat stores, scans
no accounts, calls no model and executes no proposed route.

## Inputs stay separate

| JSONL file | One row contains | Role |
| --- | --- | --- |
| `facts.jsonl` | `entity_id`, `source_version`, `key`, JSON `value` | Caller-owned authoritative snapshot |
| `sequences.jsonl` | `memory-sequence/1`, safe `sequence_id`, `origin`, `source_ref`, `producer_id`, ordered `turns`, optional `initial_history` | Captured requests and candidate estimates |
| `outcomes.jsonl`, optional | `memory-outcomes/1`, `sequence_id`, `sequence_hash`, `archive_revision`, `origin`, `labeller_id`, `source_ref`, expected `turns` | Separately attributed retrieval/route contract labels |

A sequence origin is `authored`, `captured` or `public`. Each turn contains a
normal `Task` record, `required_keys`, explicit candidate records and a
`routing_epoch`. Task inputs must name `entity_id` and `source_version`. Optional
turn fields are `critical_change`, `restart`, `required_capabilities` and
`history_events`; the latter are caller-supplied prior events, not invented text.
An outcome turn names its `task_id`, exact `facts`, `missing` keys and nonempty
`allowed_routes` (a null route represents abstention). Facts and missing keys
must partition the requested keys. Expected turns cover the whole sequence.

Closed fields, duplicate JSON keys, non-finite numbers, duplicate sequence/task
identities and unsafe sequence filenames are rejected before replay. Explicit
files have a 32 MiB limit. Source-version conflicts are rejected across the full
external archive, even when working-memory references would have been evicted.
Retrieval returns detached values and the named `memory.archive_integrity/1`
verifier checks exact membership of that supplied snapshot. This proves snapshot
integrity, not whether the supplied facts are true or still applicable.

`sequence_hash` is `hash_input(sequence_record)` and `archive_revision` is
`VersionedFactArchive(fact_records).revision`. Labels must match both fingerprints.
Their own hash is part of the outcome verifier version. Labels marked `outcomes`
by the same ID as the sequence producer cannot supply a verdict. Different IDs
and declared origins are attribution, not authenticated identity or proof of
independence. An authored label remains authored over a captured request.

## Run the public authored schema example

```bash
PYTHONPATH=src python examples/memory_replay.py \
  --sequences docs/fixtures/memory-replay/sequences.jsonl \
  --archive docs/fixtures/memory-replay/facts.jsonl \
  --outcomes docs/fixtures/memory-replay/outcomes.jsonl \
  --cost-margin 0.02 --out runs/memory-replay-labelled
```

The samples are explicitly authored and fictional. Omitting `--outcomes` replays
them without declaring success. Use a fresh output directory for each run.
The default cost margin is zero; a positive margin is opt-in. In a real capture,
candidate estimates must share a unit and estimation basis, and `routing_epoch`
must change when that basis, tools or models change. Confidence remains declared.

Each episode stays intact in the harness's seeded development/held-out split;
working references and route state reset between episodes. A `restart` revalidates
the reference checkpoint and resets route persistence inside one episode. The
baseline performs independent stateless exact retrieval; each arm applies the
same capability requirements. Context limits still apply to the compact arms:
an overflow is a measured failed run, not a fabricated zero-size context.

`report.json` retains source/label attribution, all three input revisions, code
hashes, local timing and aggregate prepared UTF-8 context metrics. If an arm
fails, its aggregate context size is unknown. Missing/dependent labels yield
`no_verdict`, never an invented pass. `BenchmarkCase.verifier=None` makes this
possible without a second orchestrator and cannot reuse another case's verifier.

Source files are unchanged. No raw tasks, facts or history are saved in the
measurement/observation/report files or printed by the CLI. Reports do contain
declared sequence and attribution IDs: use suitable IDs and keep private reports
in the ignored `runs/` directory. Passing another explicit output location is
the caller's choice; the adapter does not publish or upload it.

These are offline retrieval/route contract results, not model answer quality.
The baseline payload contains caller-supplied history plus current facts; the
compact payload adds per-fact proof metadata, so short contexts can grow. UTF-8
bytes are not token counts. Provider cost and tokens remain unknown; CPU timing
is local single-pass replay. A timing claim from the generic harness never opens
the explicit production saving gate, which remains refused.

On 3 October 2026, the three public Botte trajectory records were rejected by
the sequential contract. Their task results, timestamps and declared
`tokens_saved` do not supply versioned facts or independent sequence outcomes.
The importer is ready; TASK-110 still needs an authorized sequence corpus and
real usage measurements. See [the dated evidence](../wiki/MEMORY_REPLAY_2026-10-03.json).
