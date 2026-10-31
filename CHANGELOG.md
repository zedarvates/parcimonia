# Changelog

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
