# Changelog

## Unreleased

### Fixed

- Support mounting and initializing a completely empty Atlas remote by creating
  a deterministic local bootstrap commit, while rolling back partial submodule
  state when mounting fails.
