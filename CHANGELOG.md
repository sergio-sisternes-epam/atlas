# Changelog

## Unreleased

### Added

- Optional `relates_to[].ref` is a per-edge git rev. Absent `ref` is still tip. Present `ref` is not compiled and does not fail when the path is gone from HEAD. Relation `ref` is not mount `ref`.
- `atlas ref show` prints a store path at a git rev. `atlas ref prune` drops named failed-path pages from tip, retargets inbound tip links to one summary, and keeps history on that summary's `ref` edges.
- Runtime modules **history**, **version-hint**, and **prune**. Recall, remember, and terminate hand off to those cards. Claim A grain stays deferred.
- Memory layers **frame**, **gist**, and **memory**: `memory` is the memory
  episode type; `gist` summarises exactly one parent memory page
  (`relates_to` kind `derived_from`); each folder with one or more gists has
  exactly one frame grouping those gists (`relates_to` kind `related`). A
  lone gist still gets a frame; zero gists means no frame. No `gists/` or
  `frames/` directory is required; no gist of a gist; frame members are
  gists only.
- Legacy type `document` is kept and reported on the new memory rung as the
  legacy durable object, not auto-retyped.
- Compile severity `info`: optional `memory.rung` is `info` by default,
  `warn`, or `error`. Findings `legacy_document`, `missing_gist`,
  `gist_parent`, and `frame_members` are info and do not change the exit
  code at the default rung. `warn` reports them as warnings (exit 1, which
  does not fail the merge gate). `error` reports them as critical (exit 2,
  which fails the gate). Absent rung is `info`. Existing stores are not flipped.
- Path **memory-migrate** (`references/paths/memory-migrate.md`): assess or
  inventory a document-era store toward memory layers, or apply a named
  batch only when the operator asks. Assess and inventory write nothing.
- CLI `atlas schema memory-rung --set info|warn|error`: the only writer of
  the `memory` SCHEMA block.

### Fixed

- `atlas ref prune` accepts `--ref` only when the resolved commit is an ancestor of HEAD, including HEAD itself. A later or unrelated commit with the same page bytes is not the pre-prune snapshot.
- Memory-layer gist and frame checks ignore `relates_to` items that carry `ref`. A history edge does not satisfy a tip parent or frame-member contract.
- A prune rewrite that cannot delete its displaced temp exchanges the original page back before failing. If that undo fails, the completed exchange is still rolled back with the rest of the prune.
- After an atomic rewrite or drop rename, prune rechecks the destination name and bytes. A page whose bytes changed, including one that reused the installed inode number, is not reported as a successful retarget. That destination is left in place, and the displaced page is kept for recovery.
- `atlas ref prune` keeps the parent directory locked through a drop deletion and refuses the drop if that name reappears before the old page is deleted.
- `atlas ref prune` includes the summary in `rewritten` when appending history edges changes that page.
- `atlas ref show` and `atlas ref prune` require an Atlas store root and refuse a managed directory used as `--root`, including a custom `staging_dir`.

### Changed

- Package `description` now matches the README lede.
- Atlas CI no longer requires `APM_READ_TOKEN`. Marketplace registration and
  consumer `apm install` run unauthenticated against public github.com. Public
  consumers still need no PAT.

### Removed

- Path `query` and root CLI commands `search` and `query` (hard cut, no
  alias): use path `recall` and `atlas recall run` instead.

## 0.13.0-beta.2 - 2026-10-04

Sergio corrected the shipped memory model on 2026-10-04: the memory episode
type id is `memory`, not `page`, and every folder with at least one gist
requires exactly one frame grouping those gists. A lone gist still gets a
frame; a folder with zero gists has no frame.

## 0.12.0 - 2026-09-13

### Added

- Runtime modules **help** and **getting-started**: bundled versioned
  references explain Atlas with no store mounted; no-target help lists the
  installed registry; named help reads only the relevant source; unknown
  names are explicit; optional read-only Atlas enrichment on gaps does not
  mount, init, schema-install, remember, commit, or push.
- Root README header banner at `docs/atlas-banner.jpg`.
- GitHub issue and pull request templates for bugs, features, and contribution
  checks.
- Document Atlas's Apache-2.0 license and the separate licensing boundary for
  the `okf` dependency.

### Changed

- `atlas resolve` fails closed when a mesh path escapes the active git
  repository, when there is no git repository, or when a pointer/`subpath`
  leaves the registered mount. Grep search skips markdown that resolves
  outside the store root (symlink escape).
- Root `README.md` follows the family outline: Why / what this is not,
  Install, Use, Modules, Related, Contributing, License. Use is a session
  `/atlas` ask. Extra depth stays in `SKILL.md` and `CONTRIBUTING.md`.
- Consumer README install is marketplace-only: register
  `sergio-sisternes-epam/atlas-marketplace` as `atlas` and install
  `atlas@atlas`. `--name atlas` is required. Contributor pip setup and
  optional git-tag install stay in `CONTRIBUTING.md`. OKF stays a
  separate dependency.
- Atlas CI **Release readiness decision** now runs on pull requests. Same-repo
  PRs record `release_readiness_decision=pr-validated` when Python tests, APM
  package integrity, and consumer installs succeed. Exact-main / ready-to-tag
  remains for `main` and tags. Fork PRs still skip APM and consumer jobs
  (no `APM_READ_TOKEN`) and the readiness job records `blocked`.

## 0.11.2 - 2026-09-10

### Changed

- Resolve the `okf` format-authority dependency through marketplace `atlas`
  (`okf@atlas`) instead of `sergio-sisternes-epam`.
- Consumer registration uses
  `apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas`.

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
