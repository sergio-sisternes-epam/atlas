# Changelog

## 0.13.0-beta.13 - 2026-10-07

- CI ref surfaces (the reusable workflow default and both
  `references/ci/` examples) now point at `v0.13.0-beta.13` and match the
  package version again, which restores a releasable tag with this release.
  The existing `v0.13.0-beta.12` tag is immutable and references an older
  commit whose CI refs still lag, so validation for that tag still fails.
- `scripts/release_readiness.py --pre-tag` applies the strict `--tag` checks
  against `v<package version>` and reports `tag_readiness: pass|blocked`.
  It also blocks when the expected tag already exists at a different commit,
  so a failed tag requires advancing the package version.
  Atlas CI runs it on every build and reports `pre_tag_decision=ready to tag`
  on `main` only when it passes. A blocked manual run fails, while ordinary
  pushes to `main` only warn.
- The `--pre-tag` gate now fails closed: only a genuinely missing tag ref
  counts as free, while a tag that cannot be peeled to a commit or a git
  error blocks. Atlas CI checks out full history so older tags are visible,
  and its blocked reason is now the generic `pre-tag check failed`.
- The release workflow leaves an existing GitHub release for the tag
  unchanged instead of failing, and warns when its prerelease flag differs.
  It now fails when that existing release is still a draft, instead of
  finishing green with nothing published.

## 0.13.0-beta.12 - 2026-10-06

- The four-layer model stays optional progressive disclosure. An index may
  exist with or without a schema. Memory and other types may omit a gist.
  Non-memory types are not forced through a typed middle extension. A
  residual `missing_gist` stays expected and does not fail optimise
  (`missing_gist_fails_run: false`).
- When optimise fills, same-folder peers that already `relates_to` each
  other, or that share a `work_id`, get one useful gist. `derived_from`
  lists every parent (N≥1). Cross-folder `relates_to` does not join a
  cluster. A folder may hold more than one cluster. A gist description is
  still a verbatim substring of at least one memory parent. Schema is
  required when a gist is created, not for bare index membership.
- Thin evidence, titled stubs, and invented bodies still do not clear
  `missing_gist`. Critical or high scan hits refuse promotion. A medium
  `booking_manage_reference` is a handoff. Receipts for fills that happen
  add `scan_gate_refuse_count`, `body_fills`, `shared_gist_count`,
  `cluster_size_hist`, `enrich_optional_count`, `zero_crit_high_promoted`,
  and `{path, type, severity}` hits. The store write stamp stays
  `0.13.0-beta.7`. Sleep and consolidate remain unimplemented.

## 0.13.0-beta.11 - 2026-10-06

- Path `atlas-optimise` now fills upper layers from an evidence pack and still
  tidies the beta.10 repairs. Fill can create a gist for every compile
  missing-gist type and a minimal-prose schema when a folder has gists and no
  schema. The gist description is a verbatim parent description or the first
  claim line. Thin evidence is a handoff. A leftover `missing_gist` is
  expected and does not fail the run. Optimise never invents prose and never
  edits parent claim text.
- Modes are `path` (default, fill on), `full` (`--target .` only, serial
  only), `custom` (`--custom-tree` path prefixes), and `incremental` (git
  commit history, committer clock, default `--since-hours 24`). Dirty and
  uncommitted parents are excluded from incremental fill. `--tidy-only` skips
  fill. `--auto-verbatim` is required before a verbatim fill is `auto`;
  confirm stays the default.
- Plan and apply still refuse a stale HEAD or file hash, including every
  evidence source. A security scan blocks secret-class text and
  `sensitivity: restricted` pages. The default cost ceiling is 200 pages
  examined. The receipt records fetch OK, the git tip, counts, residuals,
  the scan, and cost against the ceiling.
- The helper stays standalone. `atlas.py` has no optimise command, and
  install, init, compile, and memory-migrate never call it. The store write
  stamp stays `0.13.0-beta.7`. Sleep and consolidate remain unimplemented.

## 0.13.0-beta.10 - 2026-10-05

- `memory-migrate apply --batch contract-file` now accepts an unstamped full
  beta.2 init (`SCHEMA.json` with `templates` and `types.recommended`
  including `frame`, no `atlas_release` key, no `memory` key) when the store
  has no content page of type `frame`, `gist`, `page`, or `memory`. Assess
  and inventory report lineage `empty-beta2-init`, `contract_file_eligible:
  true`, and `beta_content_pages: []`. Apply writes the current contract
  shape (`CONTRACT.json`, `atlas_release` `0.13.0-beta.7`, `memory.layers`
  `["schema", "gist", "memory"]`) and aligns templates and
  `types.recommended` with a fresh `atlas init` (`frame` and `page` removed,
  `schema` and `memory` added) while keeping store-specific settings and
  custom types. Existing content pages are not rewritten.
- Stamped `0.13.0-beta` / `0.13.0-beta.2` stores, stores with `memory.layers`
  `frame`/`gist`/`page` or `frame`/`gist`/`memory`, and full beta.2 inits
  that already contain those content pages still refuse with
  `in_beta_not_legacy` and are left byte-for-byte unchanged. An unreadable
  page, a non-string type, or an ambiguous template path fails closed with
  no partial write. The store write stamp stays `0.13.0-beta.7`.

## 0.13.0-beta.9 - 2026-10-05

- Path `atlas-optimise` now takes an explicit target (one folder or the store
  root) and runs a dry-run plan first. It writes one migration task list per
  top-level folder outside the store, then applies only what the operator
  approves. Pages that already share a parent no longer end the run.
- Four-layer repair with existing page text only: remove index cues to
  missing pages (such as a deleted `frame.md`), cue schema pages from
  `index.md`, add a gist to its folder's only schema, drop dead schema
  members, and copy the memory description verbatim up into a stale gist.
  Memory text is never edited; anything without source text hands off to path
  remember. Direct gist and memory cues in `index.md` are removed only on
  confirm. Suffix renames are opt-in and rewrite every inbound link.
- Subject clustering by naming (shared filename stems, operator-named subject
  folders, `work_id` folders). Moves need confirm, a free filename, a
  non-layer page, and no `atlas://` mention; links are rewritten.
- New standalone helper `scripts/atlas_optimise.py` (`plan`, `apply`). apply
  refuses a stale plan (HEAD or file hash changed) and refuses while a store
  still needs memory-migrate. It is not an `atlas.py` command and install,
  init, compile, and memory-migrate never call it. It writes no contract file:
  the store write stamp stays `0.13.0-beta.7`.

## 0.13.0-beta.8 - 2026-10-04

- Four operator paths help agents use the locked four-layer model:
  atlas-memorise, atlas-recall, atlas-forget, and atlas-optimise. They are
  paths in this package, not separate packages and not a new memory layer.
  The store write stamp stays 0.13.0-beta.7. Nothing here runs on install or
  compile.

## 0.13.0-beta.7 - 2026-10-04

- Package versions and the stamp written by `atlas init` and operator-chosen
  `memory-migrate apply --batch contract-file` now agree at `0.13.0-beta.7`.
  The `CONTRACT.json` shape and layers `schema`/`gist`/`memory` are unchanged;
  beta.3 and beta.4 remain current readers, and apply never restamps them.
  Unknown stamps (including beta.6) still fail closed. SCHEMA 2.0 behavior
  and the fleet pin `v0.12.0` are unchanged.
- Frame conversion preserves long plain descriptions without YAML wrapping
  and checks the full converted frontmatter with the store's existing reader.
  A failed round-trip exits 2 with `frame_description_not_round_trippable`,
  preserves the frame and contract, and stages the original description plus
  explicit operator steps. No migration is triggered by install, compile,
  or schema upgrade; existing page types and multiple-schema coverage stay
  unchanged.

## 0.13.0-beta.6 - 2026-10-04

- Current-shape recall now progressively discloses `index → schema → gist →
  memory` and stops at the first level that answers. The folder `index.md` is
  a schema cue list, not copied memory or a hot list of every gist; work hubs
  stay outside the memory walk.
- Remember cascades new or contradicted memories up through their owning gist
  and schema. Same-folder gists may be covered by multiple schemas; each
  schema is cued from `index.md`. Current-shape `.schema.md`, `.gist.md`, and
  `.memory.md` suffixes are search handles; frontmatter `type` remains the
  contract. Compile checks uncovered gists, missing schema index cues, and
  stale gist descriptions using the exact specified gates.
- `memory-migrate` creates suffixed schema pages and adds their index cues.
  Package surfaces move to v0.13.0-beta.6; the current-store write stamp
  remains `atlas_release` `0.13.0-beta.4` and existing beta.3 readers remain
  supported.

## 0.13.0-beta.5 - 2026-10-04

- `atlas init` and `memory-migrate apply --batch contract-file` now write
  `atlas_release` `0.13.0-beta.4` for the current contract shape (not
  `0.13.0-beta.3`, which was misleading since beta.3 had already shipped
  without this write). Readers still accept an existing `0.13.0-beta.3`
  stamp on `CONTRACT.json` with layers `schema`/`gist`/`memory` as current
  — `compute_stamp_shape` and `classify_lineage` both resolve it to
  "current", and `memory-migrate apply` on such a store is a no-op (it does
  not rewrite the stamp to beta.4). `SCHEMA.json` still refuses to carry
  either stamp; the current contract shape is written to `CONTRACT.json`
  only. Package and CI pins move to v0.13.0-beta.5.

## 0.13.0-beta.4 - 2026-10-04

- `memory-migrate` now recognizes existing `memory`, `gist`, or `frame` pages
  when reporting lineage for an unstamped pre-beta contract. The named
  `contract-file` batch still performs the beta.3 contract transition without
  rewriting existing pages, and creates one `schema` page in each folder
  containing gists so the migrated store satisfies the beta.3 schema-folder
  invariant.

## 0.13.0-beta.3 - 2026-10-04

### Added

- Optional `relates_to[].ref` is a per-edge git rev. Absent `ref` is still tip. Present `ref` is not compiled and does not fail when the path is gone from HEAD. Relation `ref` is not mount `ref`.
- `atlas ref show` prints a store path at a git rev. `atlas ref prune` drops named failed-path pages from tip, retargets inbound tip links to one summary, and keeps history on that summary's `ref` edges.
- Runtime modules **history**, **version-hint**, and **prune**. Recall, remember, and terminate hand off to those cards. Claim A grain stays deferred.
- `CONTRACT.json` is the 0.13.0-beta.3 WRITE model root contract (type/key
  contract, not a JSON Schema document). New `atlas init` writes
  `CONTRACT.json` and does not write `SCHEMA.json`; it sets `atlas_release`
  to `0.13.0-beta.3` and `memory.layers` to `["schema", "gist", "memory"]`,
  with recommended types `schema`, `gist`, and `memory` (episode type id is
  `memory`, not `page`).
- Readers accept exactly one contract filename: both `SCHEMA.json` and
  `CONTRACT.json` present, or neither present, fail compile closed (finding
  id `schema_present`). Shipped 0.13.0-beta stays readable byte-for-byte:
  `SCHEMA.json`, layers `frame`/`gist`/`page`, episode type id `page`,
  one gist still gets a frame (same as beta.2 and beta.3 `schema_folder`).
- Stamp/shape agreement (finding id `stamp_shape`): `SCHEMA.json` with
  layers `frame`/`gist`/`page` (`atlas_release` absent or `0.13.0-beta`) is
  shipped-beta; `SCHEMA.json` with `atlas_release` `0.13.0-beta.2` is
  in-beta even if types differ; `CONTRACT.json` with `atlas_release`
  `0.13.0-beta.3` and layers `schema`/`gist`/`memory` is the beta.3 shape.
  Any other combination fails compile closed. Existing fixtures with
  `SCHEMA.json`/`frame`/`gist`/`page` and no stamp keep compiling under the
  old frame rules unchanged.
- On the beta.3 shape only, `schema` is the renamed `frame` (finding id
  `schema_folder`): one gist still counts — a folder with one or more
  gists has exactly one `type: schema` page, a folder with zero gists has
  none, and a second `schema` in a gist-bearing folder fails. This rule
  does not apply to shipped-beta `SCHEMA.json` stores, which keep
  `frame_members` (one gist still counts) unchanged.
- CLI `atlas memory-migrate --operation assess|inventory|apply [--batch
  <token>]`: the pre-beta -> beta.3 contract-file migration path (path id
  `memory-migrate`). `assess`/`inventory` write nothing and report
  `lineage` (`pre-beta`, `in-beta`, or `current`). `apply` refuses an
  unscoped/unattested request (no `--batch`, or `"migrate everything"`)
  and writes nothing; refuses an in-beta store (finding id
  `in_beta_not_legacy`) and leaves its bytes unchanged; is a no-op on a
  current store; and, on a pre-beta store with `--batch contract-file`,
  renames `SCHEMA.json` to `CONTRACT.json` and stamps `atlas_release` /
  `memory.layers` to the beta.3 shape without rewriting other pages.
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
