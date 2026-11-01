# Parcimonia Local 0.4.2 — submission candidate

Observe local capacity, compare supplied route evidence and rank supplied source
context. The tools are `parcimonia_local_hardware`, `parcimonia_local_plan` and
`parcimonia_local_context`. Python 3.10+ must already be available as `python`.
All runtime implementation files are bundled; no project checkout or Botte installation
is required. The separate Parcimonia library 0.5.1 has a broader API than this plugin.

No route executes, no model loads and no project file is read by these three tools.
The context cache is bounded process memory; see [privacy](PRIVACY.md). The client/model
can receive inputs/results, so this does not promise a fully offline conversation.

The package includes a portable root manifest and Codex compatibility overlay with
matching metadata, local MCP wiring, icons, licences, provenance and exact file hashes.
The portable OpenAI extension is authoritative when the host recognizes it.

For a disposable test profile only, register the containing marketplace with the real
Codex CLI, install this plugin, verify its owned skill/cache, then list and call its
bundled MCP tools in a new local session. Do not overwrite an active profile, bypass
trust review or register a standalone MCP as a substitute for plugin ownership.
Code and schema checks are not a clean desktop installation proof.

For the authored test inputs, run `python -I -B review/generate_inputs.py` from
this directory. Its stdout contains each tool name and its input object. P3 is
called twice in one server process. The synthetic route fixture deliberately uses
an all-a hardware key and current timestamps; it is not a real benchmark. Refresh
only these example timestamps immediately before testing, not actual measurements.

See [submission status](PUBLICATION.md), [getting started](skills/get-started/SKILL.md),
[review cases](review/test-cases.json), [licences](THIRD_PARTY_NOTICES.md) and
[validation scope](docs/validation-scope.md). No hooks, credentials or model weights
are included. The ZIP is not automatically submitted or published.
