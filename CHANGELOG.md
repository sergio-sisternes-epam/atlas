# Changelog

## Unreleased

## 0.9.0 - 2026-09-06

### Fixed

- Support mounting and initializing a completely empty Atlas remote by creating
  a deterministic local bootstrap commit, while rolling back partial submodule
  state when mounting fails.

### Changed

- Clarify that activation cards must be rendered as fenced Markdown `text`
  blocks, including their opening and closing fences.
