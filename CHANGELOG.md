# Changelog

## Unreleased

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
