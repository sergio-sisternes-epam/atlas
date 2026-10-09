# Changelog

## Unreleased

### Added

- Optional `relates_to[].ref` is a per-edge git rev. Absent `ref` is still tip. Present `ref` is not compiled and does not fail when the path is gone from HEAD. Relation `ref` is not mount `ref`.
- `atlas ref show` prints a store path at a git rev. `atlas ref prune` drops named failed-path pages from tip, retargets inbound tip links to one summary, and keeps history on that summary's `ref` edges.
- Runtime modules **history**, **version-hint**, and **prune**. Recall, remember, and terminate hand off to those cards. Claim A grain stays deferred.

### Fixed

- `atlas ref prune` treats a quoted `relates_to` key as the same list, and leaves an indented `- path:` bullet inside a block scalar untouched. A history scan uses that same item indentation, so prose is not a second edge.
- `atlas ref prune` accepts `--ref` only when the resolved commit is an ancestor of HEAD, including HEAD itself, and the worktree bytes match that blob and the HEAD blob. A later or unrelated commit, or a dirty worktree that only matches the older rev, is not the pre-prune snapshot.
- Memory-layer gist and frame checks ignore `relates_to` items that carry `ref`. A history edge does not satisfy a tip parent or frame-member contract.
- A prune rewrite that cannot delete its displaced temp exchanges the original page back before failing. If that undo fails, the completed exchange is still rolled back with the rest of the prune.
- After an atomic rewrite or drop rename, prune rechecks the destination name and bytes. A page whose bytes changed, including one that reused the installed inode number, is not reported as a successful retarget. That destination is left in place, and the displaced page is kept for recovery.
- A drop rename that moves a different inode keeps the checked page bytes and mode in a recovery file, then puts the other file back. The checked page is not closed away as the only remaining copy.
- A restore link whose destination is replaced before the identity check keeps the checked temp instead of unlinking the last copy.
- Optimise ignores `relates_to` items that carry `ref` when deciding gist coverage, gist parents, schema members, and cluster joins. A history edge does not suppress `uncovered-gist`.
- `atlas ref prune` rechecks the tip with a dry-run compile after deletion. Any remaining critical finding rolls back only the pages prune wrote or deleted. A concurrent edit on another page is left in place.
- `atlas ref prune` keeps one lock file for the mutation window and does not replace that inode between runs. It opens that lock without following a symlink.
- A failed prune keeps rolling back every page it wrote or deleted. A page that cannot be restored is left for recovery, and the command reports that aggregate failure.
- Optimise referrer discovery and rewriting leave ref-bearing `relates_to` items unchanged. A history edge still names the pre-move path.
- `atlas ref prune` treats a markdown link that starts with `/` as store-root relative. It does not consult that path on the filesystem root, so an inbound `/dead.md` link is retargeted before the page is deleted.
- A quoted SCHEMA 2.0 `ref` key is still a history edge. Prune and optimise leave that item's path unchanged.
- Optimise and prune treat history as a parsed top-level `relates_to` `ref`. Nested prose or a nested mapping that contains `ref:` does not freeze a live path.
- Optimise and prune rewrite only a relation item's top-level `path`. A `path:` line inside a block scalar is prose. An item that cannot be parsed is left unchanged.
- `atlas ref prune` rolls back when the post-mutation compile gains a blocking warning. A warning already present, and the non-blocking unmounted-atlas warning, do not by themselves undo the prune. Critical findings still fail the gate.
- `atlas ref show` and `atlas ref prune` load without `fcntl`, so other commands still start where file locking is unavailable. Prune refuses there instead of failing at import.
- `atlas ref prune` keeps the parent directory locked through a drop deletion and refuses the drop if that name reappears before the old page is deleted.
- `atlas ref prune` includes the summary in `rewritten` when appending history edges changes that page.
- `atlas ref show` and `atlas ref prune` require an Atlas store root and refuse a managed directory used as `--root`, including a custom `staging_dir`.

## 0.13.1 - 2026-10-09

### Fixed

- Atlas overlays may carry one package-metadata **extension slot**.
  Its root key is the `contribution_id` with `-` replaced by `_`
  (`atlas-tasks` → `atlas_tasks`). Since v0.10.0, `schema install` on a
  contract envelope 2.0 (`schema_version` 2.0) store rejected such overlays
  with `$: Unevaluated properties are not allowed`, although the overlay docs
  allowed extra root keys and SCHEMA 1.0 stores accepted them. As a result,
  released atlas-tasks overlays (v0.2.0 to v0.6.1) could not be installed on
  2.0 stores. The slot must be a JSON object (`overlay_extension`
  otherwise). It is never merged into the effective contract and core never
  reads it. A second overlay that claims the same key is still an
  `overlay_key_clash`. Ids whose slot would equal a core or envelope key,
  such as `memory` or `atlas-release`, get no slot.
- On SCHEMA 2.0, every other extra overlay root key is still rejected,
  including `x-` prefixed keys and another package's slot. The error now
  adds a hint that names the allowed extension key.
- `schema upgrade --to 2.0` now checks installed overlays against the 2.0
  rules. A store whose overlays would fail compile after the upgrade (for
  example a generic `kva` root key) previews `ok=false` with the overlay
  errors in `target_errors`, and `--apply` refuses with zero writes.
  Previously the upgrade succeeded and the next compile failed `schema_v2`.
  The upgrade also validates every installed overlay against
  `contribution-v1` (the 2.0 envelope), as a 2.0 `schema install` would, so
  an overlay such as `"claimed_folders": [1]` now blocks it with the overlay
  path in `target_errors`.
- `schema install` now takes the store's `.atlas-upgrade.lock` while it
  validates and writes. While the lock is held, by an upgrade or another
  install, it exits 2 with zero writes. `schema upgrade --apply` rechecks
  installed overlays after acquiring the lock and before any write, so an
  install that races the upgrade can no longer leave a 2.0 store that fails
  compile. When the lock is already held, apply refuses with a clear message
  instead of a traceback. `schema uninstall` now takes the same lock for its
  whole read and delete, and exits 2 with zero writes while it is held, so it
  can no longer remove an overlay, such as `atlas-compat-v1`, after an
  upgrade's recheck. `schema new`, `schema memory-rung --set`,
  `init --force` on an existing store and `memory-migrate --operation apply`
  (both the `contract-file` and `restamp` batches), `recall activate` and
  `recall disable` also write `schema.d/` or the contract file, so they now
  take the same lock and exit 2 with zero writes while it is held. Recall
  activate and disable read the contract file only after taking the lock, so
  they can no longer lose a concurrent `schema memory-rung --set`,
  `init --force` or `memory-migrate` write on a 2.0 store. Previously `schema new atlas-compat-v1` could run
  after an upgrade's recheck, and the upgrade then overwrote that overlay
  and its receipt and still reported success.
- The lock now carries a unique token. A command that takes it only
  removes a lock whose token matches the one it wrote. Apply no longer reclaims an
  existing lock when the contract already reads 2.0: since v0.10.0 that let
  a second, concurrent upgrade delete the first upgrade's live lock. Every
  existing lock is treated as held. A lock left by an interrupted run must
  be removed by an operator; the error message says when that is safe.
- The `schema_type_contract` warning now names the store's contract file
  (`CONTRACT.json` on current stores) instead of always `SCHEMA.json`.

### Docs

- Path `schema` lists the overlay root keys allowed on 1.0 and 2.0 stores,
  documents the extension slot, its minimum reader and rollback steps, the
  `overlay_extension` issue and the shared store lock and the verbs that take it,
  and asks packages to test overlays on both store versions. Path `configure` notes
  that installed overlays can block the upgrade, that apply rechecks them
  under the lock, and that a kept slot needs Atlas >= 0.13.1 after the
  upgrade.
- Path `schema` gains step 3a "Shipping an Atlas overlay in an APM
  package": `apm install` a pinned tag only installs the package and never
  mounts its overlay; locate the package root
  (`apm_modules/<owner>/<pkg>/`, `apm.lock.yaml`), run `schema install` on
  the named store, re-run it (with `--force` when required keys change)
  after an upgrade, and use `schema uninstall` because `apm uninstall`
  leaves the overlay in the store. The step notes that the `schema` verbs
  and file names mean the store contract, not the `*.schema.md` memory
  layer; the CLI verbs and file names stay as they are in this release.
  SKILL.md and help `getting-started` link to it.
- `contribution-v1.schema.json` gains a `$comment` that describes the slot
  and says it is never merged into the effective contract. Its `$id` and
  its closed shape are unchanged.
- Paths `help`, `init`, `ci` (SKILL.md) and `references/README.md` now
  name the store's contract file, `CONTRACT.json` or `SCHEMA.json`, where
  they named only `SCHEMA.json`, as the CLI already does: the help
  enrichment root needs exactly one readable, valid contract file, and
  `store init` fails closed on an existing `atlas` branch without one.
- SKILL.md and the four-level disclosure scenario no longer name a
  `gist_without_schema` compile gate. Uncovered gists fail `schema_folder`.
- New fixtures `fixtures/contributions/` hold released overlays verbatim.
  `scripts/test_overlay_extension.py` installs and compiles every fixture on
  SCHEMA 1.0 and 2.0 stores, and through a 1.0 → 2.0 upgrade.

### Compatibility

- **Minimum reader for extension slots on SCHEMA 2.0.** Atlas v0.13.0 and
  earlier merge the slot as a generic root key, so their compile fails
  `schema_v2` (`'atlas_tasks' was unexpected`) on a SCHEMA 2.0 store that
  holds an overlay with a slot. That covers a slot overlay installed by
  v0.13.1 and one kept through a v0.13.1 `schema upgrade --to 2.0`. The
  contract stamp does not record this, so such a store needs Atlas >= 0.13.1
  to compile. On a 2.0 store, `schema install` prints a note when it
  accepts a slot.
- To roll back or mix versions on such a store, first reinstall a slot-free
  overlay (atlas-tasks >= 0.6.2) with `schema install`, or `schema uninstall`
  the overlay. Older readers then compile it again.
- SCHEMA 1.0 stores are unaffected: older readers accept extra overlay root
  keys there.

### Unchanged

- The contract stamp stays `0.13.0`: `atlas init` still writes
  `atlas_release` `0.13.0`, and a `0.13.1` stamp still fails closed. No
  store migration is needed. v0.13.0 readers are unaffected, except on
  SCHEMA 2.0 stores that hold an extension-slot overlay (see
  Compatibility).
- SCHEMA 1.0 stores keep accepting generic extra overlay root keys as
  before. The only difference is that the extension slot is no longer
  copied into the effective SCHEMA.
- Apart from the package version, help baselines and CI ref pins, which
  move to `0.13.1` / `v0.13.1`, the `schema install` note and the
  `schema_type_contract` finding path above, no release surface changes.

## 0.13.0 - 2026-10-09

Final 0.13.0 release. Over v0.12.0 the beta series ships:

- The four-layer memory model `index → schema → gist → memory`, as
  optional progressive disclosure: an index may exist without a schema,
  a page may skip the gist, and a residual `missing_gist` is not a
  completeness failure. Recall stops at the first level that answers.
- `CONTRACT.json` as the current root contract file, with stamp/shape
  agreement (`stamp_shape`): exactly one of `SCHEMA.json` and
  `CONTRACT.json`, known stamps only, unknown and malformed stamps fail
  closed, and shipped `0.13.0-beta` and `0.13.0-beta.2` stores keep
  reading as before.
- CLI `atlas memory-migrate --operation assess|inventory|apply`: assess
  and inventory write nothing; apply needs an explicit batch. The
  `contract-file` batch moves a pre-beta store, or an empty unstamped
  beta.2 init, to `CONTRACT.json` and adds the schema pages and index cues
  it needs without rewriting existing pages.
- Operator paths `atlas-memorise`, `atlas-recall`, `atlas-forget` and
  `atlas-optimise`, which help agents use the four-layer model.
- The standalone helper `scripts/atlas_optimise.py` (`plan`, `apply`) with
  an explicit target, modes `path`, `full`, `custom` and `incremental`,
  fill from evidence under the four-layer soft model (verbatim gist
  descriptions, minimal-prose schemas, and fill-when-sensible same-folder
  shared gists), a security scan, stale-plan refusal and a cost ceiling.
  It is not an `atlas.py` command and never writes the contract file.
- Bundled runtime help and getting-started baselines (shipped in v0.12.0)
  updated for the four-layer model, `memory-migrate` and the new operator
  paths; they still work with no Atlas mounted.
- Release tooling: the `scripts/release_readiness.py --pre-tag` gate and
  idempotent GitHub release creation that fails closed on a draft.
- Docs-branch guards that keep `site/` off `main` and out of every
  release tag (see below).

Changes in this release:

- `atlas init` and `memory-migrate --operation apply --batch
  contract-file` now write `atlas_release` `0.13.0` (previously
  `0.13.0-beta.7`) on `CONTRACT.json` with `memory.layers`
  `["schema", "gist", "memory"]`. Stores stamped `0.13.0-beta.3`,
  `0.13.0-beta.4` or `0.13.0-beta.7` stay current on read and need no
  migration; apply with no batch or with `--batch contract-file` is still
  a zero-write no-op on them. `SCHEMA.json` refuses `0.13.0` like every
  other current stamp, and unknown stamps such as `0.13.0-beta.6`,
  `0.13.0-rc.1` or `0.13.1` still fail closed.
- New opt-in `memory-migrate --operation apply --batch restamp` moves a
  current store's stamp from beta.3, beta.4 or beta.7 to `0.13.0` and
  changes nothing else: it replaces only the top-level stamp value inside
  the original `CONTRACT.json` bytes (spacing, line endings and literal
  non-ASCII kept), writes them through an atomic replace that keeps the
  file mode and never writes through a symlink, and touches no page,
  template or other file. Any other unsupported `--batch` value, such as
  `restmap`, now exits non-zero with zero writes on current stores too,
  instead of falling through to the no-op. It is an
  idempotent no-op on a `0.13.0` store and refuses
  (`restamp_not_eligible`) with zero writes on pre-beta, in-beta,
  `SCHEMA.json`, symlinked or unknown-stamp stores, and
  (`restamp_not_byte_safe`) with zero writes when that single-value
  replacement cannot be verified, such as duplicate keys or a nested
  `atlas_release` carrying the same old stamp. Assess and
  inventory now report `atlas_release` and `restamp_eligible`. Restamp
  only after every reader of that store runs Atlas 0.13.0, because
  `0.13.0-beta.13` and earlier packages fail closed on the new stamp.
  Compile and `scripts/atlas_optimise.py` only read the stamp.
- Package version, help baselines and CI ref pins move to `0.13.0` /
  `v0.13.0`.
- No dedicated sleep or consolidate command ships. Scheduling
  `scripts/atlas_optimise.py plan --optimise-mode incremental` is the
  interim, operator-chosen routine; it is not a sleep feature.
- Docs-branch guards keep `site/` off `main` and out of every release tag:
  a new `no-site-guard` CI job fails unless the default branch is `main`,
  no `site/` or `DOCS_BRANCH*` file is tracked and `docs-site.yml` is still
  the stub; the release workflow checks the default branch and the tagged
  tree before publishing; `.gitattributes` adds `site/ export-ignore` for
  archives; and a disabled T1 `docs-site.yml` stub plus `notify-docs` job
  prepare the docs-branch build.

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
