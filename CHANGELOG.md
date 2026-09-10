# Changelog

## Unreleased

## 0.11.1 - 2026-09-10

### Changed

- Pin the Atlas help pilot design, activation-card and retrieval-fallback
  decisions, and curated Cartograph onboarding articles in the knowledge store.
- Connect Atlas and Cartograph knowledge stores with reciprocal help links;
  align mesh refs and submodule tracking with the published knowledge branches.
- Preserve the pilot as knowledge and design only: runtime `help`,
  `getting-started`, and `visualise` activation paths remain unimplemented.

## 0.11.0 - 2026-09-10

### Added

- Storage strategy: **shared** (consumer `atlas` branch, default for new `atlas store init`) or **dedicated** (separate store repo). Mesh `strategy` field; missing means dedicated.
- `atlas store init` / `atlas store rehost`. Path init defaults to shared. Path migrate requires `migrate_mode: relocate | strategy`. CLI `atlas migrate` remains staging import.
- GitHub driver after shared git: ruleset blocking direct push to `atlas`. Self-hosted / missing `gh`: warn and continue.

### Changed

- Default `atlas store init` strategy is shared. Existing mesh rows without `strategy` stay dedicated.

## 0.10.0 - 2026-09-09

### Added

- SCHEMA 2.0 opt-in Semantic Memory Recall (scan, SQLite FTS5, bounded graph retrieve).
- `atlas schema upgrade`, `atlas recall *`, `search --profile` / `--allow-partial`, and path `configure`.
- `atlas:tgrep` coarse driver: local argv `tgrep index`/`search` against `.atlas-index/tgrep/`, rebuilt on projection digest mismatch; never `serve`.
- Recall query fast path: skip YAML projection when the published generation's cheap fingerprint matches; mismatch auto-rebuilds.

### Changed

- Default `atlas init` remains SCHEMA 1.0. Existing search/query behaviour is unchanged until recall is enabled.
- `atlas recall activate` defaults to `atlas:ranked`. `atlas:tgrep` stays an explicit advanced profile.
- Query/configure guidance: grep until opt-in; after a published generation, `atlas:ranked` is the recommended next engine (speed and follow-up tokens). Provenance: atlas-atlas lesson `lessons/2026-09-09-opt-in-ranked-after-fast-path.md`.
- `jsonschema` floor is 4.18; PyYAML is required for SCHEMA 2.0 frontmatter.

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
