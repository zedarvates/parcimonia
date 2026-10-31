# Changelog

## Integration into main — 2026-10-31

- Merge 0.5.0 while retaining the newer asset catalogues, native-media probes,
  memory capture/replay, local text/vision clients and feasibility constraints.
- Keep both suites: the release regression tests and all existing main tests.
- Preserve current backlog and wiki entries while restoring the release's public
  label-review/span-retrieval exports. No labelled corpus or route is promoted.
- Include the portable contributor instructions and exact-byte Git attributes in
  source distributions. The published v0.5.0 tag and its assets stay unchanged.
- Correct Windows catalogue refusal of existing dangling output links, preserve
  byte-exact worker errors, bound adversarial pytest IDs, and make refusal tests
  deterministic without depending on host TCP refusal timing.
- Report expected platform/absent-native-tool test skips explicitly; installed
  native-tool failures and unexpected skips still fail archive qualification.
- Accept numbered FFprobe release-tag versions such as `n9.0.2` while retaining
  the observed version, minimum major version and existing resource limits.
- Recognize Windows Tesseract `v5` version strings, and interrupt a TLS deadline
  without clearing SSL state concurrently with the handshake. Both have focused
  regression coverage; model-call, retry and native execution limits stay intact.
- Install native fixture backends in CI so OCR, PDF and media integration tests
  execute rather than disappear behind absent optional executables. Windows SDK
  archives are pinned by release URL and SHA-256, only within disposable CI jobs.

## 0.5.0 — 2026-10-31

- Package the complete current Parcimonia library, including the existing local
  compute, context, execution-profile, task-preparation and continuation modules.
- Provide the installed `parcimonia` command for the existing JSON recipes, with
  `--version` matching the distribution and Python API.
- Reject duplicate JSON keys, non-finite numbers and inputs larger than 16 MiB
  before opening a recipe database or a decision cache. Apply the same checks to
  recorded answers and stdin. Return JSON errors and exit code 2.
- Run the generated review-script check directly with Node, without requiring RTK.
- Define explicit wheel/source contents and an offline archive qualification
  command: exact source inventory, byte-identical rebuild from the source archive,
  isolated installation, full tests, CLI and extracted plugin stdio checks.

The independent Parcimonia Local plugin remains at 0.4.1, with its original file
inventory. No model, provider, automatic production routing or shared service is
enabled by this release. See [release qualification](docs/RELEASE.md).
