# Changelog

## Unreleased (targets 0.14.0)

- FTS5 queries (`--engine bm25`, `atlas:ranked` and other FTS5 profiles)
  are tokenised like the index's `unicode61` tokenizer instead of keeping
  only ASCII letters, digits and `_`. `café`, `résumé`, `Grüße` and `東京`
  are no longer cut to `caf`, `r AND sum` or an empty query, `cafe` and
  `café` find each other, and `_` separates terms as it does in the index.
  A contiguous CJK run stays one term, so `東京` is not found inside `東京都`.
- Index freshness is decided by content: the corpus digest is now sha256
  over sorted `<relative path> NUL <sha256 of the bytes>` lines, and an
  index or generation counts as current only when its recorded digest
  equals the current one. The path/size/mtime fingerprint is only a fast
  pre-check that can rule an index stale, never fresh, so a same-length
  edit that keeps its mtime is no longer served from the old generation.
  This covers the fts5 fast path (recall, `--engine bm25`, `atlas graph`),
  the preferred-engine refresh, nanograph reuse, legacy `.atlas-index/`
  reuse and `atlas index show` / `status`. The digest is hashed from raw
  bytes once per command. It also covers the projection inputs: the bytes
  of `SCHEMA.json` / `CONTRACT.json`, the `schema.d/*.json` overlays and a
  `PROJECTION_VERSION`, so a schema-only change (for example SCHEMA 1.0 to
  2.0, a new relation vocabulary or recall field config) makes the index
  stale and recall, graph and nanograph rebuild with the new parse, while
  files outside the projection inputs do not. The fts5 pointer now records
  `format` 2 and nanograph's index `format` is now 4, so generations
  recorded with an older digest rebuild once.
- `atlas graph neighbours PAGE`, `graph edges --from PAGE` and `graph edges
  --to PAGE` refuse an exit-state page (`terminated`, `deprecated`,
  `superseded`) with exit 2 unless `--include-exits` is passed, for example
  "starting page old/dead.md is in exit state terminated; pass
  --include-exits to traverse from it". The check runs before driver
  dispatch, so `--driver nanograph` behaves the same.
- Ignore guard failures are reported: an unreadable or unwritable
  `info/exclude` (or `info` that is not a directory) or a failing `git
  rev-parse` gives the warning `atlas_indexes_ignore_failed`
  (`atlas_index_ignore_failed` for the legacy guard) from compile/validate,
  `atlas index build` / `set --build`, recall auto-create and nanograph and
  tgrep builds. It is never treated as already ignored, the index is still
  built and exit codes do not change. `atlas index show` / `status` report
  `ignore: ok|missing|failed` from `git check-ignore`.
- `atlas-mesh.json` writes (`index set`/`unset`, mount's row upsert, store
  removal) are serialised by `<project>/atlas-mesh.json.lock`, the
  owner-token lock now shared with index builders (`core/owned_lock.py`):
  the file is re-read under the lock, validated and replaced atomically, so
  concurrent writers no longer lose updates. A stale lock (60 s, or a dead
  pid) is taken over; a held lock makes a writer wait up to 10 s and then
  exit 2 without writing. The lock and temp-file patterns are added to
  `info/exclude`. Mount's row upsert and store removal now also write
  atomically.
- nanograph runs in isolation: every nanograph call (`--version`, `init`,
  `load`, `run`) runs in a private, empty, 0700 `atlas-nanograph-*`
  temporary directory that is removed afterwards, so nanograph never loads
  `.env.nano` or `.env` from your project, store or home directory. `init`
  reads a private schema copy; `nanograph.toml` / `.env.nano` that `init`
  scaffolds into an inferred project directory are removed (existing files
  are kept and reported in `driver_note`), and generations are scrubbed of
  `.env.nano`, `.env` and `nanograph.toml` before `load` and before
  publishing. Previously `init` wrote both files into the published
  generation.
- `atlas graph neighbours --driver nanograph` now reports nanograph build
  warnings such as `atlas_indexes_ignore_failed` in `warnings` (and once on
  stderr in text mode), as recall does; the exit code is unchanged.

- CLI bounds: `atlas graph nodes --limit`, `atlas graph neighbours
  --max-nodes/--max-edges` must be at least 1 and `--hops` must be 1..3;
  other values are Click usage errors (exit 2). A negative limit is no
  longer treated as unlimited, and the in-process graph API raises
  `ValueError` for a cap or limit below 1 instead of disabling it.
- Security: every external driver subprocess (nanograph's `--version`
  probe, `init`, `load` and `run`) now gets an allow-listed environment from
  one helper (`core/drivers/subprocess_env.py`): only `PATH`, `HOME`, temp,
  locale, user, Windows system, `RUST_BACKTRACE`, `RUST_LOG` and `NO_COLOR`
  pass, and a deny pass removes GitHub tokens (`ATLAS_PAT`, `GH_*`,
  `GITHUB_*`, `COPILOT_*`), model API keys and anything named like a
  token, secret, password or credential. Atlas's GitHub tokens no longer
  reach nanograph. See `references/drivers.md`, External driver
  environment.
- Security: the driver platform gate always uses the real platform.
  Production code reads no environment variable for it; tests use an injectable provider and the
  test-only entry `scripts/testing/atlas_test_cli.py`.
- nanograph detection resolves `ATLAS_NANOGRAPH_BIN` (relative values
  against the current directory) and the `PATH` match to an absolute path,
  so builds and queries that run in the index directory find the binary.
- Index builder locks carry an `owner` token: only the owner releases a
  lock, stale takeovers rename the old lock aside one at a time, and a
  builder that lost its lock publishes nothing and reports `lock_lost`
  (readers keep the old pointer). Release now re-checks ownership and
  removes the lock under the same `<name>.takeover` guard as stale takeover.
  The guard has its own owner token, only its creator removes it, and an
  abandoned guard is broken after 30 s. A takeover can no longer slip
  between a release's check and its rename, which used to move the new
  owner's lock aside briefly, so that owner saw it as lost and aborted a
  legitimate build. A failed `still_owned()` read is confirmed once under
  the guard before `lost` is set. This applies to index builders and
  `atlas-mesh.json.lock`. Publishing now also runs under that guard: the
  final ownership check, the `current.json` replace and pruning (fts5,
  including profile stores and `atlas index build`, and nanograph), and the
  `atlas-mesh.json` replace, happen in one short critical section, so a
  writer whose stale lock was taken over can no longer overwrite the new
  owner's pointer, prune its generation or replace its mesh change. It
  reports `lock_lost` instead (exit 2 for mesh writes). Pruning keeps the
  previous pointer's generation, and a cheap-fingerprint refresh of the
  fts5 pointer is written only under the free lock, never over a newer
  pointer.
- `atlas graph neighbours --driver nanograph` budgets its work:
  `--max-nodes` / `--max-edges` now bound the nanograph `run` calls, not
  just the output. Only relation kinds present in the projection (or
  given with `--kind`) are queried. Calls stop as soon as a cap is certain
  to be hit, or once a call budget or a 120 s overall deadline is reached.
  The result then has `truncated: true` and a `driver_note`. Uncapped
  results still match `native-graph` exactly.
- `atlas-mesh.json` validation rejects duplicate store ids (compared after
  normalisation and ignoring case), naming both rows and their paths. Mount,
  `atlas index` (exit 2) and recall refuse such a file instead of letting
  two stores share one index directory.
- Preferred recall engine: a consuming project can set
  `"recall": {"engine": "grep|bm25|nanograph"}` on a store row of its
  `atlas-mesh.json` or as a project-wide top-level default, or set
  `ATLAS_RECALL_ENGINE`. Precedence is `--engine` > `ATLAS_RECALL_ENGINE` >
  store row > project default > built-in default (SCHEMA
  `query.search_engine` when `bm25`, else `grep`), resolved in one place
  (`core/engine_preference.py`). Recall payloads add `engine_requested` and
  `engine_source` (`cli|env|store|project|default`) alongside
  `engine_used`, `driver_used` and `driver_note`.
- Auto-created, self-refreshing indexes: with an indexed engine (bm25 ->
  `fts5`, nanograph -> `nanograph`) recall builds the index under
  `.atlas/indexes/<driver-type>/<atlas-id>/` when it is missing or its corpus
  digest (or nanograph version) changed, and publishes it before answering.
  `atlas compile` / `validate` (not `--dry-run`) and `atlas index build`
  refresh the preferred index and report `preferred_index_refreshed`
  or `preferred_index_fresh`; a failure is the warning
  `preferred_index_failed` and never changes exit codes. Builds take a
  `.lock` (stale after ten minutes), write a `.tmp-*` sibling and publish
  with an atomic rename plus an atomic pointer replace; fts5 now prunes to
  the current generation plus one, and nanograph gains a `current.json`
  pointer. Unavailable preferences fall back nanograph -> bm25 -> grep with
  a `driver_note` and exit 0; no index is built for an unavailable driver.
- New `atlas index` command group to manage the preferred engine and its
  indexes without editing `atlas-mesh.json` by hand:
  `atlas index set <grep|bm25|nanograph> [--store <atlas-id> | --default]
  [--build]` writes `recall.engine` on a store row (the store at `--root`,
  or `--store` with any spelling that normalises to the row id) or as the
  project-wide default, warning `engine_unavailable_here` (exit 0) when the
  engine cannot run on this machine and, with `--build`, building the
  affected indexes now; `atlas index unset` removes it (idempotent, index
  files are left for you to delete); `atlas index show` reports the value
  per level, the winning engine and source, the effective engine and why,
  any overriding recall profile and index freshness
  (`fresh|stale|missing|legacy-only`); `atlas index status` tabulates every
  store row and the project default; `atlas index build [--store <atlas-id>
  | --all] [--force]` builds or refreshes the effective engine's index
  (exit 1 when any build failed, others still attempted). Writes touch only
  the target's `recall` key, keep key and row order, indentation and the
  trailing newline, skip unchanged values and replace the file atomically;
  invalid files are refused without writing.
- Deprecated: `atlas recall index build` is now an alias of
  `atlas index build` for the store at `--root` (same payload plus a
  `deprecated_command` warning); it will be removed after 0.14.x.
- New environment variable `ATLAS_RECALL_ENGINE` (invalid values exit 2 for
  `recall run`, naming the variable and the allowed values).
- Mesh schema: optional `recall` object (only `engine`) on store rows and at
  the top level of `atlas-mesh.json`. Unknown keys or values are rejected
  with an error naming the file, the store id or "project default", and the
  allowed values. Mesh files without `recall` are unchanged.
- Behaviour change: an explicit `--engine bm25` now persists its FTS5 index
  in the project and refreshes it on change instead of building a temporary
  index per query. The temporary index remains only as a fallback when the
  index location cannot be written or another builder holds the lock
  (`ephemeral: true`, reason in `driver_note`).
- Stores with an enabled recall profile keep the profile authoritative: a
  `bm25` preference is a no-op (the profile index uses the same new location
  and auto-refresh), a `nanograph` or `grep` preference is reported as info
  `preferred_engine_ignored`, and explicit `--engine` still exits 2 with a
  message pointing to `--profile`.
- `atlas recall run --engine bm25` now ranks with SQLite FTS5 on stores
  where recall is not enabled (SCHEMA 1.0, or 2.0 with recall disabled).
  It reuses a published generation when its corpus digest matches the
  current content, otherwise it projects the current tree into a temporary index that is
  deleted after the query. Field filters and exit-state exclusion match
  grep mode, filter-only queries keep grep behaviour, and the payload
  reports `engine_used: "sqlite-fts5"`, `score_orientation`, `ephemeral`
  and `fast_path`. It falls back to grep with a warning only when FTS5 is
  unavailable or projection fails. The "BM25 engine not yet implemented"
  stub is gone. Grep stays the default when no flag is passed, and
  `--engine` still conflicts with enabled recall.
- Labelled any-word retry: in `--engine bm25` and in the SMR
  `sqlite-fts5` path, when an all-words query with two or more tokens
  has no eligible match, one any-word (OR) query runs. Eligibility
  (field filters, `path:`, the exit-state rule) is pushed into the FTS5
  query through a temporary table of allowed page ids, so both passes
  collect eligible hits up to the limit and an eligible all-words match
  ranked behind excluded pages is never dropped or relabelled `any`. The
  payload carries `match: "all"` or `match: "any"`, and each retried hit
  carries `match: "any"`. The FTS5 driver gains an `operator` parameter
  (AND by default), an `allowed` parameter and the shared
  `search_eligible` helper used by both paths.
- Index ignore guards: `atlas compile` / `validate` (not `--dry-run`),
  `atlas index build` and every nanograph or tgrep build add
  `/.atlas/indexes/` (or `/<rel>/.atlas/indexes/` when the project root is
  below the work-tree top level) to the project repository's
  `info/exclude` when no existing line (such as `.atlas/`) covers it, and
  report an `atlas_indexes_ignored` info item only when they added the
  line. For this release the legacy guard still adds `/.atlas-index/` (or
  `/<store>/.atlas-index/`) to the store repository's `info/exclude` and
  reports `atlas_index_ignored`. A committed `.gitignore` is never edited,
  non-git roots are left alone, and exit codes are unchanged. A guard that
  fails reports a warning (see the ignore guard failure entry above).
- Docs: `SKILL.md` and path `recall` describe the FTS5-backed
  `--engine bm25` and the any-word retry; BM25 is no longer listed as a
  non-goal.
- New read-only command group `atlas graph` for structural lookups over
  the shared projection (`relates_to` plus top-level frontmatter). It
  works on every store (SCHEMA or CONTRACT, 1.0 or 2.0, recall on or off),
  reads a matching published generation when there is one
  (`fast_path: true`) and otherwise projects the tree in memory. It never
  writes to the store. `--allow-partial` turns projection errors into
  exit 1 with `complete: false` and an `omitted` list.
  - `atlas graph nodes` filters pages with repeatable, ANDed
    `--where field=value` on normalised scalar text (list fields match
    any element), plus `--path` and `--limit`.
  - `atlas graph edges --from|--to|--all [--kind K]` lists edges in
    authored direction with `resolved` and `external` flags; unresolved
    edges are never dropped and a leading `./` is normalised.
  - `atlas graph neighbours PAGE` is a bounded, cycle-safe breadth-first
    walk with `--direction in|out|both`, `--hops 1..3`, `--kind`,
    `--where` (filters returned nodes, not traversal), `--max-nodes` /
    `--max-edges` and `truncated`.
  - `atlas graph export --format json|nanograph --out DIR` writes a
    byte-stable `graph.json`, or a nanograph v1.3.0 `schema.pg`,
    `seed.jsonl` and `export-receipt.json` (unresolved edges listed in
    the receipt). DIR inside the store is refused. Edge type names are
    collision-free: kinds whose PascalCase names clash (`foo-bar` and
    `foo_bar`, or `foo-external` and the external variant of `foo`) each
    get a stable `X<8 hex of sha256>` suffix, and the receipt records the
    map as `edge_types: [{kind, external, edge_type}]`.
  - The recall exit-state rule (`terminated`/`deprecated`/`superseded`
    hidden unless `--include-exits` or explicitly asked for) applies to
    every verb except export.
- Shared helpers: `projection.normalise_target`, and
  `retrieve.is_exit_page` / `is_visible` / `adjacent` used by both the
  recall neighbourhood and `atlas graph`. The recall neighbourhood now
  also resolves `relates_to` targets written with a leading `./`.
- Docs: new `references/graph.md`; `SKILL.md` lists the `atlas graph`
  verbs and routes structural questions to them, and path `recall` notes
  that `atlas graph neighbours` gives the Expand step as structured JSON.

- Driver overlay (`core/driver_overlay.py`): one driver interface
  (`id`, `capabilities`, `platforms`, `external`, `detect`, `build`,
  `bm25_search`, `neighbours`, `health`; unsupported capabilities raise
  `NotSupported`), a registry with the built-in `sqlite-fts5`
  (bm25_search) and `native-graph` (graph_traversal) drivers as the
  defaults on every platform, and a platform matrix. macOS arm64 has
  nanograph; darwin x86_64, linux x86_64, linux aarch64 and win32 AMD64
  are empty slots (`planned: none`).
- Optional nanograph driver, macOS arm64 only, nanograph 1.3.0 or newer
  (`ATLAS_NANOGRAPH_BIN` or `nanograph` on PATH). It is never selected
  implicitly and never runs on another platform, even with the binary on
  PATH. Argv-only subprocesses with timeouts, an allow-listed
  environment (see below), no `.env.nano`. Its index lives under
  `<project-root>/.atlas/indexes/nanograph/<atlas-id>/<generation>/`
  (export, generated `atlas.gq`,
  `atlas.nano`, `ready.json`), is reused while the corpus digest, version
  and index format match, and only the two newest generations are kept.
  Its `bm25_text` query has no row cap, so Atlas filters every
  positive-scoring page before cutting to the limit. Neighbour queries use
  the export's collision-free edge type map and report the original Atlas
  kinds; colliding kinds no longer fall back to `native-graph`.
- `atlas recall run --engine nanograph` (where `--engine bm25` is
  allowed) ranks with nanograph BM25 (`score_orientation:
  "higher_better"`, same field filters and exit-state rule). When
  nanograph is unavailable or fails it falls back to the sqlite-fts5
  path with `driver_used: "sqlite-fts5"` and a `driver_note`, exit 0.
  `--engine bm25` payloads now also carry `driver_used`.
- `atlas graph neighbours --driver native|nanograph` (default `native`)
  with the same fallback; payloads carry `driver_used`. New
  `atlas graph drivers [--json]` lists the registry, platform matrix and
  detection results.
- Docs: new `references/drivers.md`; `SKILL.md` lists `--engine
  nanograph`, `--driver` and `atlas graph drivers`.
- Derived indexes move out of the store into the consuming project:
  `<project-root>/.atlas/indexes/<driver-type>/<atlas-id>/` with driver
  types `fts5` (published recall generations), `nanograph` and `tgrep`.
  The project root and atlas id come from the `atlas-mesh.json` row whose
  `path` is the store (mesh mode), otherwise from the store's git
  work-tree top level and its `origin` id, or the store directory with a
  `local/<name>-<hash>` id (standalone mode); `ATLAS_INDEX_ROOT` (absolute)
  overrides the project root. Ids are validated segment by segment and
  symlinked index paths are refused. `current.json` pointers are now
  relative to the index directory. Payloads that report an index gain
  `index_dir` and `index_location` (`mode`, `atlas_id`, `id_source`).
  Projection and validation skip `.atlas/`. New single source of truth
  `core/index_location.py`; docs in `references/drivers.md` (Index
  location).
- Deprecated: the in-store `.atlas-index/` (`recall/`, `nanograph/`,
  `tgrep/`). For 0.14.x Atlas still reads a usable index there, read-only
  and only when the new location has none, with a `legacy_index_location`
  warning; the next build writes the new location only. Support is
  removed after 0.14.x. Atlas never deletes it: remove `.atlas-index/`
  yourself after rebuilding.

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
