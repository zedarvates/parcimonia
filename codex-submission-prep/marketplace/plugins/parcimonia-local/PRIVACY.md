# Privacy — Parcimonia Local

This three-tool desktop package processes supplied queries, document text/paths/hashes,
host capacity observations and caller-supplied route measurements. It does not read
project files or accept project-root configuration. The publisher receives no runtime
data through a plugin network connection: the plugin itself makes no network/model calls.

Context selection keeps at most 128 entries / 4 MiB of serialized derived terms,
counts and symbols in process memory. Derived vocabulary can be private. Full source
text and queries are not cached. Supplied bytes are rechecked before reuse. This
cache disappears when the process exits; Python/buffer memory can exceed its payload budget.
Route reports are not persisted. No runtime transcript, telemetry file or disk index is written.

Hardware observation reads general CPU/RAM/commit/disk capacity and optional NVIDIA
GPU names/memory through nvidia-smi. Its timestamp supports freshness checks; its
hardware hash summarizes configuration, not a serial number or user/account identifier.
The driver utility has independent behavior. No model or accelerator is qualified by name.

Codex and the selected model provider can receive arguments and returned results under
their own policies. Local processing does not establish an offline conversation. Supply
only authorized task-specific source data; do not include credentials or regulated data.
Stop the plugin process to clear its memory. Support issues are submitted separately by
the user to the public project; do not post private source, keys or personal identifiers.
