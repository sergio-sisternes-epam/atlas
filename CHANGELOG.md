# Changelog

## Unreleased

### Added

- Opt-in per-type required H2 sections and nonempty content checks, scalar and
  calendar-date rules, date ordering, and typed local `relates_to` constraints.
- `atlas schema configure --max-required-sections-per-type` for validated,
  atomic core budget changes without permitting overlay overrides.
- `atlas schema capabilities --json` for executable feature/version preflight.

### Fixed

- Preflight overlay installations before writes; upgrade only unchanged,
  receipt-hash-owned templates. User edits and unowned conflicting templates
  remain protected even with `--force`.
- Preserve template ownership across repeated installs and preserve edited or
  legacy unhashed templates on uninstall.

## 0.9.1 - 2026-09-08

### Changed

- Resolve the `okf` format-authority dependency through the
  `sergio-sisternes-epam` marketplace catalog instead of a git SHA pin.
- Require APM CLI 0.30.0 in CI and contributor setup.
- Scan source APM primitives without `--frozen` / `--ci` identity checks;
  disposable consumers remain the lockfile and drift gate.

## 0.9.0 - 2026-09-06

### Fixed

- Support mounting and initializing a completely empty Atlas remote by creating
  a deterministic local bootstrap commit, while rolling back partial submodule
  state when mounting fails.

### Changed

- Clarify that activation cards must be rendered as fenced Markdown `text`
  blocks, including their opening and closing fences.
