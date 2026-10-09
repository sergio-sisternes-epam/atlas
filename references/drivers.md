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

The platform comes from `sys.platform` and `platform.machine()` only; `arm64`
and `aarch64` are treated as the same machine. The gate always reflects the
real platform: no environment variable or setting can change it. Only the
test suite swaps the platform, in process or through the test-only entry
`scripts/testing/atlas_test_cli.py` (`ATLAS_TEST_PLATFORM`), which the
production entry `scripts/atlas.py` never loads. The rows marked
`planned: none` are slots for a future driver, not commitments. The built-ins
cover every row.

## nanograph

nanograph (MIT, `github.com/nanograph/nanograph`) publishes release
binaries for `aarch64-apple-darwin` only, so Atlas enables it only on
macOS arm64. Atlas does not install it.

- **Binary:** `ATLAS_NANOGRAPH_BIN` when set, otherwise `nanograph` on
  `PATH`. Detection turns either into an absolute, resolved path (a
  relative `ATLAS_NANOGRAPH_BIN` is resolved against the current directory
  at detection time) and every later call uses that path. Minimum version
  1.3.0, read from `nanograph --version`.
- **Detection reasons** (`atlas graph drivers` shows them), checked in this
  order: `unavailable on <platform>-<machine>` (the platform check comes
  first; a binary on `PATH` is never run on an unsupported platform),
  `nanograph binary not found`, `nanograph version unreadable`,
  `nanograph version <v> below minimum 1.3.0`, `ok`.
- **Process rules:** argv only, never a shell; timeouts of 10 s
  (`--version`), 120 s (`init`, `load`) and 30 s (`run`); every path on
  argv is absolute. The environment is
  allow-listed (see [External driver environment](#external-driver-environment)),
  for the `--version` probe as well as `init`, `load` and `run`. Atlas never
  writes `.env.nano`.
- **Working directory and env-file isolation:** nanograph loads `.env.nano`
  and then `.env` from its working directory at startup (and reads
  `nanograph.toml` from there). So every call (`--version`, `init`, `load`,
  `run`) runs in its own private, empty directory that Atlas creates with
  `tempfile.mkdtemp(prefix="atlas-nanograph-")` under the system temp
  directory (mode 0700) and removes afterwards. Atlas refuses the call if
  that directory holds `.env.nano` or `.env`. nanograph therefore never
  reads env files from your home, project or store directories, and a
  secret in a project `.env` never reaches it.
- **Scaffolding clean-up:** `nanograph init` writes `nanograph.toml` and
  `.env.nano` (when missing) into the directory it infers: the common
  ancestor of `--db` and `--schema`, or its working directory when that
  ancestor is the filesystem root. Atlas passes `init` a copy of the schema
  in the private working directory (the generation keeps `export/schema.pg`
  for provenance), so the ancestor is normally the root and the files land
  in the private directory. When it is a real directory (for example
  `TMPDIR` inside the project), Atlas computes it the same way, records
  which of the two files already exist there, and after `init` deletes only
  the ones `init` created. Your own files are never deleted; when one sits in
  the inferred directory Atlas reports a `driver_note`. Before `load` and
  again before publishing, Atlas removes any `.env.nano`, `.env` or
  `nanograph.toml` from the whole temporary generation directory, so a
  published generation never contains them.
- **No embeddings, no network:** the export has no `Vector` fields and no
  `@embed`, and Atlas only uses BM25 and graph queries.
- **Index:** `.atlas/indexes/nanograph/<atlas-id>/<generation>/` under the
  project root (see [Index location](#index-location)), where `<generation>`
  is the first 16 hex characters of the projection `corpus_digest`. A build
  writes `export/` (the `atlas graph export --format nanograph` files),
  `atlas.gq` (generated queries), `atlas.nano` (`nanograph init` then
  `nanograph load --mode overwrite`) and finally `ready.json`
  (`format`, `version`, `corpus_digest`, `built_at`; `format` is the
  index layout version, bumped when the generated queries, edge type
  naming or the corpus digest change, so an older generation is rebuilt
  rather than reused; format 3 is the content digest below). The build runs in a
  `.tmp-<generation>` sibling under an owner-checked `.lock` (see path
  `recall`, Atomic publish and lock), is renamed into place
  atomically and then `current.json` (generation, digest, version) is
  replaced atomically; a rebuild for the same digest after a version change
  gets a `-<8 hex>` suffix. A generation is reused while the pointer (and
  its `ready.json`) matches the digest, version and format; the pointer's generation
  plus the newest other one are kept and older ones deleted. Symlinked index paths are refused, and a
  build never writes outside `.atlas/indexes/nanograph/<atlas-id>/`.
- **Queries:** `bm25_text($q)` ranks pages on `text`; rows with score 0 or
  less are dropped and scores are higher-better. The query has no `limit`:
  every positive-scoring page comes back, Atlas then applies the `type:`,
  `path:` and exit-state filters, and only then cuts to the requested
  limit, so eligible pages ranked behind many ineligible ones are never
  lost. (Atlas does not rely on offset pagination, which is not part of the
  query syntax it uses.) Graph traversal uses one
  generated query per edge type and direction
  (`neighbours_out_<edge>` / `neighbours_in_<edge>`, edge name with a
  lowercase first letter). Edge types come from the collision-free map in
  `references/graph.md` (nanograph mapping), and each result is mapped back
  to its original Atlas kind, so kinds such as `foo-bar` and `foo_bar` stay
  distinct. Atlas merges the results in the same breadth-first walk as
  `native-graph`, so the output matches it exactly.

## External driver environment

Every external driver subprocess gets an environment built by one helper,
`external_driver_env()` in `scripts/atlas_cli/core/drivers/subprocess_env.py`.
It never inherits Atlas's own environment.

1. **Allow-list.** Only these variables pass, and only when already set:
   `PATH`, `HOME`, `TMPDIR`, `TMP`, `TEMP`, `LANG`, `LC_ALL`, `LC_CTYPE`,
   `TZ`, `USER`, `LOGNAME`, `SYSTEMROOT`, `WINDIR`, `COMSPEC` (for future
   Windows slots), `RUST_BACKTRACE`, `RUST_LOG` and `NO_COLOR`.
2. **Deny pass** (defence in depth; it wins over the allow-list). A
   variable is removed when it is one of Atlas's GitHub token variables
   (`TOKEN_ENV_KEYS` in `core/auth.py`) or its name matches, ignoring case,
   `TOKEN`, `PAT` (as a whole `_`-separated word, so `PATH` is kept),
   `SECRET`, `PASSWORD`, `CREDENTIAL`, `API_KEY`, or starts with `GH_`,
   `GITHUB_`, `GITHUB_APM_PAT`, `COPILOT_`, `ATLAS_PAT`, `NANOGRAPH_EMBED`,
   `OPENAI_`, `GEMINI_`, `ANTHROPIC_`, `AZURE_OPENAI_` or `AWS_`.

So GitHub tokens, model API keys and unrelated variables never reach
nanograph. A future external driver uses the same helper.

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
or, for nanograph, the binary version changes.

**Freshness is decided by content.** The corpus digest is sha256 over the
sorted lines `<relative path> NUL <sha256 of the file bytes>` of every
eligible page, so an edit, rename, addition or removal changes it, even an
edit that keeps the byte length and restores the old mtime. An index or
generation counts as current (fts5 fast path for recall, `--engine bm25`
and `atlas graph`; preferred-engine refresh; nanograph `ready.json` reuse;
legacy `.atlas-index/` reuse; `atlas index show` / `status`) only when its
recorded corpus digest equals the current one. The cheap
path/size/mtime fingerprint stored in the pointer is only a fast pre-check:
when it differs the index is stale without hashing, but a match never
makes it fresh. The content digest hashes raw bytes without parsing
YAML and is computed at most once per command; a projection, when one is
needed, carries the same digest. Generations recorded before this rule
(different digest formula) rebuild once. Builds go to a `.tmp-*`
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
   is skipped, but a file with duplicate store ids that lists `S` is an
   error: index commands exit 2 and recall refuses, so two stores never
   share an index) and look for a row whose `path`, resolved against `D`,
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

A guard that cannot do its job is reported, never treated as "already
ignored": when `info/exclude` cannot be read or written (for example a
read-only file, or `info` being a file), or `git rev-parse --git-path`
fails, the command adds the warning item `atlas_indexes_ignore_failed`
(`atlas_index_ignore_failed` for the legacy guard), for example `could not
add /.atlas/indexes/ to <path>: <reason>; add it to .gitignore or
info/exclude yourself to keep derived indexes out of commits`. The index is
still built and exit codes do not change (validate treats both codes as
non-blocking). Compile/validate, `atlas index build` / `set --build`,
recall's auto-create and nanograph and tgrep builds all surface it.
`atlas index show` and `atlas index status` report `ignore: ok`, `missing`
or `failed` (with the reason; `n/a` outside git) by asking git itself
(`git check-ignore -q` on a path under `.atlas/indexes/`), so a
`.gitignore` line counts too.

**Deprecated: `.atlas-index/`.** The old in-store locations
(`.atlas-index/recall/`, `.atlas-index/nanograph/`, `.atlas-index/tgrep/`)
are read-only for 0.14.x and removed after it. When no usable index exists
at the new location but one does at the old one, Atlas reads it without
changing it and adds a `legacy_index_location` warning item (printed to
stderr outside `--json`). The next build (`atlas index build`, a
compile that publishes, or a nanograph or tgrep rebuild) writes only the
new location, after which the warning disappears. Atlas never deletes the
old directory; delete `.atlas-index/` yourself once you have rebuilt.
