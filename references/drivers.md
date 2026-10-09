# Drivers — the driver overlay

Atlas ranks text and walks the `relates_to` graph through **drivers**. The
built-in drivers run everywhere and are always the defaults. External
drivers are optional, platform-gated, and only used when you ask for them
by name. Today there is one external driver: **nanograph**, on macOS arm64.

## Driver interface

Every driver (`scripts/atlas_cli/core/driver_overlay.py`) exposes:

| Member | Meaning |
|--------|---------|
| `id: str` | Registry name (`sqlite-fts5`, `native-graph`, `nanograph`). |
| `capabilities: frozenset[str]` | Subset of `bm25_search`, `graph_traversal`. |
| `platforms: tuple[(sys_platform, machine)]` | Where the driver may run; empty means every platform. |
| `external: bool` | True when it needs a binary Atlas does not ship. |
| `detect() -> Detection` | `available`, `reason`, `version`, `binary`. |
| `build(export_dir, index_dir) -> dict` | Build the driver's own index from an Atlas export. Built-ins need none. |
| `bm25_search(store, query, limit) -> [hit]` | Ranked hits (`path`, `score`, `title`, `type`, `driver`, `score_orientation`). |
| `neighbours(store, seed, kinds, direction, hops) -> {nodes, edges}` | Same shape as `atlas graph neighbours`. |
| `health() -> dict` | `detect()` as a status record. |

Calling a capability the driver does not declare raises `NotSupported`. A
run-time failure (non-zero exit, timeout, unreadable output) raises
`DriverError`; callers then fall back to the built-in driver.

## Registry

| Driver | Capabilities | Platforms | External | Default for |
|--------|--------------|-----------|----------|-------------|
| `sqlite-fts5` | `bm25_search` | all | no | `bm25_search` |
| `native-graph` | `graph_traversal` | all | no | `graph_traversal` |
| `nanograph` | `bm25_search`, `graph_traversal` | darwin arm64 | yes | — |

`sqlite-fts5` is the `--engine bm25` path; `native-graph` is the
`atlas graph` traversal over the shared projection.

## Platform matrix

| Platform | Machine | External drivers | Planned |
|----------|---------|------------------|---------|
| macOS (`darwin`) | `arm64` | nanograph: supported | — |
| macOS (`darwin`) | `x86_64` | — | none |
| Linux (`linux`) | `x86_64` | — | none |
| Linux (`linux`) | `aarch64` | — | none |
| Windows (`win32`) | `AMD64` | — | none |

The platform comes from `sys.platform` and `platform.machine()`; `arm64`
and `aarch64` are treated as the same machine. The rows marked
`planned: none` are slots for a future driver, not commitments. The built-ins
cover every row.

## nanograph

nanograph (MIT, `github.com/nanograph/nanograph`) publishes release
binaries for `aarch64-apple-darwin` only, so Atlas enables it only on
macOS arm64. Atlas does not install it.

- **Binary:** `ATLAS_NANOGRAPH_BIN` when set, otherwise `nanograph` on
  `PATH`. Minimum version 1.3.0, read from `nanograph --version`.
- **Detection reasons** (`atlas graph drivers` shows them), checked in this
  order: `unavailable on <platform>-<machine>` (the platform check comes
  first; a binary on `PATH` is never run on an unsupported platform),
  `nanograph binary not found`, `nanograph version unreadable`,
  `nanograph version <v> below minimum 1.3.0`, `ok`.
- **Process rules:** argv only, never a shell; timeouts of 10 s
  (`--version`), 120 s (`init`, `load`) and 30 s (`run`); the working
  directory is the index generation directory. The environment is passed
  through without `OPENAI_API_KEY`, `GEMINI_API_KEY` or any
  `NANOGRAPH_EMBED*` variable. Atlas never writes `.env.nano`.
- **No embeddings, no network:** the export has no `Vector` fields and no
  `@embed`, and Atlas only uses BM25 and graph queries.
- **Index:** `.atlas/indexes/nanograph/<atlas-id>/<generation>/` under the
  project root (see [Index location](#index-location)), where `<generation>`
  is the first 16 hex characters of the projection `corpus_digest`. A build
  writes `export/` (the `atlas graph export --format nanograph` files),
  `atlas.gq` (generated queries), `atlas.nano` (`nanograph init` then
  `nanograph load --mode overwrite`) and finally `ready.json`
  (`version`, `corpus_digest`, `built_at`). The build runs in a
  `.tmp-<generation>` sibling under a `.lock`, is renamed into place
  atomically and then `current.json` (generation, digest, version) is
  replaced atomically; a rebuild for the same digest after a version change
  gets a `-<8 hex>` suffix. A generation is reused while the pointer (and
  its `ready.json`) matches the digest and version; the pointer's generation
  plus the newest other one are kept and older ones deleted. Symlinked index paths are refused, and a
  build never writes outside `.atlas/indexes/nanograph/<atlas-id>/`.
- **Queries:** `bm25_text($q)` ranks pages on `text`; rows with score 0 or
  less are dropped and scores are higher-better. Graph traversal uses one
  generated query per edge type and direction
  (`neighbours_out_<edge>` / `neighbours_in_<edge>`, edge name with a
  lowercase first letter) and Atlas merges the results in the same
  breadth-first walk as `native-graph`, so the output matches it exactly.

## Selection and fallback

Nothing selects nanograph implicitly: it is not a recall profile, not a
`query.search_engine` value and not a default. A project can prefer it (or
`bm25`) explicitly through `atlas-mesh.json` `recall.engine` or
`ATLAS_RECALL_ENGINE`, normally set with `atlas index set nanograph`
(per store) or `atlas index set nanograph --default` (project-wide); see
path `recall`, Preferred engine and Managing engines and indexes.

| Preferred engine | Driver | Index (driver type) | Fallback when unavailable |
| --- | --- | --- | --- |
| `grep` | `grep` | none | — |
| `bm25` | `sqlite-fts5` | `fts5` | `grep` (no FTS5) |
| `nanograph` | `nanograph` | `nanograph` | `bm25`, then `grep` |

Availability comes from each driver's `detect()`; Atlas never builds an index
for an unavailable driver. With a preference (or an explicit `--engine`),
recall creates the index on first use and rebuilds it when the corpus digest
or, for nanograph, the binary version changes. Builds go to a `.tmp-*`
sibling under a `.lock` and are published with an atomic rename plus an
atomic `current.json` pointer replace. On stores with an enabled recall
profile the profile wins; see path `recall`.

- `atlas recall run "<q>" --engine nanograph` (allowed wherever
  `--engine bm25` is) uses nanograph when it is available:
  `engine_configured: "nanograph"`, `engine_used: "nanograph"`,
  `driver_used: "nanograph"`, `score_orientation: "higher_better"`. Field
  filters (`type:` `kva:` `status:` `work_id:` `path:`) and the exit-state
  rule are the same as `--engine bm25`.
- `atlas graph neighbours PAGE --driver nanograph` (default `native`)
  uses nanograph traversal and reports `driver_used: "nanograph"`.
- When nanograph is unavailable or fails, both fall back to the built-in
  driver (`sqlite-fts5` / `native-graph`), report it in `driver_used`, add
  a `driver_note` (recall: `preferred engine nanograph unavailable:
  unavailable on linux-x86_64; used bm25`; graph: `nanograph unavailable on
  linux-x86_64`) and keep exit 0.
- `atlas graph drivers [--root R] [--json]` lists the registry,
  capabilities, platform matrix, current platform and each `detect()`.

## Adding a platform driver

1. Implement the interface in `scripts/atlas_cli/core/drivers/<id>.py`
   (subclass `BaseDriver`), declaring only the capabilities it supports
   and the `platforms` it runs on. Check the platform first in `detect()`.
2. Register it in `driver_overlay.registry()` and fill its row in
   `PLATFORM_MATRIX`.
3. Keep its index under `index_location.index_dir(store, "<driver-type>")`
   (add the type to `DRIVER_TYPES`), use argv-only subprocesses
   with timeouts, and raise `DriverError` on any failure so the built-in
   fallback applies.
4. Add tests that run on Linux CI with a fake binary, plus a live test that
   skips unless the real platform and binary are present.
5. Do not make it a default; built-ins stay the default everywhere.

## Index location

Derived indexes belong to the consuming project, not to the store's git
history. Every driver keeps its index under

```text
<project-root>/.atlas/indexes/<driver-type>/<atlas-id>/
```

with driver type first: `fts5` (the published recall index:
`current.json` plus `generations/<gen_id>/`, the pointer's generation and
the newest other one kept), `nanograph` (`current.json` plus
`<generation>/` as above) and `tgrep` (its index files).
`.atlas/` already holds mounted stores as `.atlas/<host>/<owner>/<repo>`, so
one project gets one index per store across the mesh. `--engine bm25` and a
preferred `bm25` persist their FTS5 index here; temporary FTS5 indexes (only
when this location cannot be written, or a build is in progress elsewhere)
live in the system temporary directory. `scripts/atlas_cli/core/index_location.py`
is the single source of truth.

**Resolution rule** for a store directory `S` (resolved):

1. **Mesh mode.** Walk up from the parent of `S` through its ancestors. At
   each directory `D` holding `atlas-mesh.json`, load it (a malformed file
   is skipped) and look for a row whose `path`, resolved against `D`,
   equals `S`. The first match wins: the project root is `D`, the atlas id
   is the row's `id` (`id_source: "mesh"`).
2. **Standalone mode** (no row matches). The project root is the git
   work-tree top level of `S` (`git rev-parse --show-toplevel`), or `S`
   itself outside git. When `S` is that top level and `remote.origin.url`
   normalises to `host/owner/repo`, that is the atlas id
   (`id_source: "origin"`). Otherwise the id is
   `local/<dir name>-<first 8 hex of sha256 of the resolved path of S>`
   (`id_source: "local"`); a store in a subdirectory of a larger work tree
   always gets a `local` id, so two stores in one repository never share an
   index. In standalone mode the index sits inside the store's own work
   tree at `.atlas/indexes/`; the ignore guard excludes it and projection
   and validation skip `.atlas/`, so it never becomes content or a tracked
   file.
3. **Override.** `ATLAS_INDEX_ROOT`, when it is an absolute path, replaces
   the project root (the id and mode are resolved as above). A relative
   value is ignored with a warning. Intended for tests and unusual layouts.

**Sanitising.** The atlas id is split on `/` and each segment must match
`^[A-Za-z0-9][A-Za-z0-9._-]*$`; empty ids, absolute paths, backslashes,
NUL, empty segments and `.` or `..` segments are refused with an error
naming the id. Ids are validated, never re-normalised. The joined
directory must stay under `.atlas/indexes/<driver-type>/`, and no existing
path component from `.atlas/` downwards may be a symlink. Nested
directories that mirror the mount layout (for example
`.atlas/indexes/fts5/github.com/owner/repo/`) are intended.

**Reporting.** Payloads that report an index (`index build`, `index show`,
`index status`,
`recall status`, compile and validate info, `--engine bm25` fast path,
`atlas graph` fast path, `atlas graph drivers`, `nanograph_index`) carry
`index_dir` (project-relative POSIX path) and
`index_location: {"mode", "atlas_id", "id_source"}`.

**Ignore guard.** `atlas compile` / `validate` (not `--dry-run`),
`atlas index build` (and its deprecated alias `atlas recall index build`)
and every nanograph or tgrep build add
`/.atlas/indexes/` (or `/<rel>/.atlas/indexes/` when the project root is
below its work-tree top level) to the project repository's
`info/exclude` (`git rev-parse --git-path info/exclude`) unless an
existing line such as `.atlas/`, `/.atlas/` or `.atlas/indexes/` already
covers it, and report `atlas_indexes_ignored` when they add the line. A
committed `.gitignore` is never edited and a non-git project root is left
alone. For this release the store's legacy `/.atlas-index/` line is still
added as before (`atlas_index_ignored`).

**Deprecated: `.atlas-index/`.** The old in-store locations
(`.atlas-index/recall/`, `.atlas-index/nanograph/`, `.atlas-index/tgrep/`)
are read-only for 0.14.x and removed after it. When no usable index exists
at the new location but one does at the old one, Atlas reads it without
changing it and adds a `legacy_index_location` warning item (printed to
stderr outside `--json`). The next build (`atlas index build`, a
compile that publishes, or a nanograph or tgrep rebuild) writes only the
new location, after which the warning disappears. Atlas never deletes the
old directory; delete `.atlas-index/` yourself once you have rebuilt.
