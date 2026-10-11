---
name: atlas/paths/recall
description: Use this path when an agent needs an answer from an Atlas store: cue a schema from index.md, then progressively open schema, gist, and memory pages, stopping as soon as the answer is present. Trigger on recall, find in the atlas, what does the store say, look up a decision or work hub, even when the user says query or search. Do not use it to write pages, compile, configure the recall index, or migrate memory layers. Invocation: FORCED when the Atlas router selects retrieval. Boundary: one path, one receipt field, no second index.
path_id: recall
---

# Path: recall

## When

Need knowledge from an Atlas (skill process memory or project store).

## Layers (do not merge)

| Name | Layer | Job |
|------|--------|-----|
| `path: recall` | B17 protocol | Card, form the ask, search, rewrite once, select, read, hop, receipt |
| `atlas recall run` | CLI tool | Ranked hits + traffic payload (text and topic questions) |
| `atlas graph nodes\|edges\|neighbours` | CLI tool | Read-only structure (structural questions) |

Card `path` is always `recall` for retrieval. **Routing inside this path:** text and topic questions use `atlas recall run`; structural questions (which pages link to X, neighbours of a page, children of a work hub, nodes by frontmatter field) use `atlas graph nodes|edges|neighbours` instead — see `references/graph.md`. Do not add a peer path named search or graph. SCHEMA 2.0 recall (`--profile`, `--allow-partial`) is configured on path `configure`, not here.

## Enter (required — Atlas `activation_card: on`)

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: recall
path_module: references/paths/recall.md
intent: <one line>
root: <atlas store root>
```

Then **read this file**. Missing card or unloaded module ⇒ incomplete Enter.

Other paths (remember, work, landscape, an Autogenesis Run) may call `atlas recall run` as a **tool** under their own card. They still must not use unbounded tree grep as primary discovery.

## Procedure

1. **Resolve root** — load path `mount` first with `atlas_id` (and `ref`) on the card. Set `--root` to what `atlas resolve <atlas_id>` prints. Never `--root` the skill tree. Omitting `--root` uses the current working directory; the CLI does not default to the mount.
2. **Cue from the index** — `index.md` is the OKF reserved directory listing and hot schema-cue list, not laboratory short-term memory (Cowan STM) and not a table of contents. Read its schema cues before opening a schema. It does not copy memory claims or pin every gist; pages not cued there remain searchable. Index and `hub.md` filenames stay unsuffixed, and a work hub is not a memory level.
3. **Progressive disclosure (index → schema → gist → memory)** — open the schema cued for the question. If it answers, stop: do not open a gist or memory page. Otherwise open only a relevant gist; if it answers, stop without opening its parent memory. Descend to a memory page only when the gist does not answer or the ask needs the record itself. Do not load every gist for one ask. On shipped `SCHEMA.json` stores, the first memory-layer page is named `frame`; on the current `CONTRACT.json` shape it is `schema`. On either shape, stop at the level in hand when it answers and do not open a lower level after a hit.
4. **Form the query** from the intent. Free text plus only justified field tokens:
   - `type:<name>` — frontmatter type, not a body mention
   - `kva:<value>` — traffic (alive, forming, terminated, …)
   - `status:<value>`
   - `work_id:<id>`
   - `path:<store-relative prefix>`
   Unknown `field:` tokens stay free text. Do not invent filters the ask does not support.
5. **Search (always run, even when the gist already answered)**
   ```bash
   python3 <atlas-skill>/scripts/atlas.py recall run "<query>" --root <root> --json
   ```
   Mesh scope (federated recall over the members of the project's `atlas-mesh.json`):
   `recall run "<query>" --root <root> --scope store|mesh [--rrf-k N] [--engine E] [--limit N] [--json]`.
   Precedence: `--scope` > top-level `recall.scope` > `store`; `--rrf-k` > top-level `recall.rrf_k` > 60 (integer 1-1000). Each member runs its own engine and index; hits carry `atlas_id` and `uri` (`atlas://<atlas-id>/<path>`, with `%`, `#`, `?` and whitespace in the path percent-encoded), excluded and `invalid` members are never read and are listed with their status and `reason`, all-words hits (tier 1) always precede any-word retry hits (tier 2), and `sensitivity: restricted` pages are never returned. `--limit 0` returns every hit from every member, whatever its engine. Exit 2 for `--profile`, `--allow-partial` or a negative `--limit` with mesh scope, `--rrf-k` in store scope, a bad k or no mesh listing the store; exit 1 with `complete: false` when a member fails. A listed root counts even when the row is excluded, has an id that is not an index path, or is a subpath or pathless row: discovery does not read that store, and with no `--scope` plus `recall.scope: mesh` recall federates and reports the member excluded or invalid (`invalid_atlas_id`) rather than reading it as a store. Explicit `--scope store` still searches that store alone, because exclusion applies only in mesh scope and the flag overrides the project setting. Overlap is lexical: a row whose path equals or contains another row's path is overlapping and is not read, except a path under a directory every walk skips, which still does not count.

   **Symlinks in mesh scope.** Cross-store symlinks inside a project are unsupported. Mesh recall and mesh page walks never follow a symlink: ripgrep is not passed `--follow` or `-L` and is not given a symlink path, and Python walks skip symlinked files and directories (`lstat` before open). A member whose root, or any component of that root inside the project, is a symlink is `invalid` with reason `symlinked_root` and is not read; a link into it is `outside_mesh`, as for any other invalid row. The same rule covers every other file mesh recall or the mesh view opens, decided with `lstat` before any open or following `stat`. A symlinked `schema.d` directory, or a symlinked `*.json` overlay inside a real `schema.d`, is optional: skipped with a warning and not merged. A symlinked `SCHEMA.json` is required: the member is `invalid` with reason `symlinked_root` and is not read. A symlinked `CONTRACT.json` is optional and is skipped with a warning; when it is the only contract file the member is `unmounted`. Recall configuration lives in that contract and in the project `atlas-mesh.json`; there is no per-member config file. Index pointers and databases (`current.json`, a generation database, a legacy `.atlas-index` pointer, and the same files for nanograph and tgrep) are optional: a symlink is skipped with a warning and recall projects the tree instead. Page walks already skip a symlinked `log.md`, `index.md` or other page; `read_page` also refuses one. Frontmatter has no include or transclusion that opens another file. `staging/` and `templates/` are pruned by name before they are listed. A `path:` filter that is a symlink is not followed. `atlas-mesh.json` is the project listing, read once at discovery and not re-read for a pinned member; a symlink listing is not followed and discovery fails closed. Store scope is unchanged and may still follow a symlink it already followed.
   For a structural question, run the matching `atlas graph nodes|edges|neighbours … --root <root> --json` here instead (`references/graph.md`).
   Run this step regardless of whether the hot list or abstraction walk already answered the ask — the exit receipt always records `recall_cmd`. Stopping at the gist (step 3) decides whether the parent memory page is opened, not whether search runs.
   Do **not** use unbounded whole-tree `grep` / `rg` / `find` as the primary discovery method. `rg` inside one already-chosen file is reading, not discovery.

   **Engine choice.** Grep is the basic default (`recall` off) and stays the default when no flag is passed. With `recall` off, `--engine bm25` ranks with SQLite FTS5 and, from 0.14.0, keeps its index on disk and refreshes it when the corpus changes (a temporary index is used only when the index location cannot be written). A configured preferred engine (see **Preferred engine** below) replaces the no-flag default. It falls back to grep with a warning only when FTS5 is unavailable or projection fails. In both `--engine bm25` and FTS5 presets such as `atlas:ranked`, one any-word retry runs only when no eligible all-words match exists (eligibility — field filters, `path:` and the exit-state rule — is applied before ranks are cut, so an eligible all-words match ranked behind excluded pages still counts); the payload says `match: "any"` and so does each retried hit, so treat those hits as weaker evidence. FTS5 queries are tokenised like the index's `unicode61` tokenizer: Unicode letters and numbers form terms (`café`, `résumé`, `Grüße`, `東京`), while punctuation, symbols and `_` separate them (`foo_bar` is `foo` and `bar`); matching is case- and diacritic-insensitive (`cafe` and `café` find each other). A contiguous CJK run is a single term, so `東京` finds `東京` written as its own word but not inside a longer run such as `東京都`; use grep for such partial matches. After opt-in, `atlas:ranked` is the next configuration: published FTS5 plus content-digest fast path (product bench ~80ms vs grep ~108ms on ~395 pages, and 4–13× cheaper follow-up reads). `atlas:tgrep` is advanced with limited benefits; do not enable it for latency (leaf `p-tgrep-serve-and-subset-rank`). Field filters beat an engine switch. Published indexes live in the project at `.atlas/indexes/<driver-type>/<atlas-id>/` (project root and id from the matching `atlas-mesh.json` row, else the store's git top level with its origin id, or the store directory with a `local/` hash id; `references/drivers.md`, Index location). A `legacy_index_location` warning means Atlas read a deprecated in-store `.atlas-index/` (read-only for 0.14.x); rebuild with `atlas index build`, then you may delete `.atlas-index/`. Provenance: atlas-atlas lesson `lessons/2026-09-09-opt-in-ranked-after-fast-path.md` (experience `experiences/2026-09-09-smr-fast-path-product-bench.md`; leaf `p-query-engine-kpis`).
6. **Rewrite (at most once)** — if the question is synthesis / why / evolve / “all ideas”, **or** top hits only *mention* the token to exclude it, run **one** extra search. Extra tokens come only from the **Search aliases** table in `glossary.md` and from titles of pages already opened. Cap extra tokens (about 6). Keep the original question in the second query. Do not invent synonyms.
7. **Select hits from the payload** — prefer spine pages and `type: work` / `decision` for status, rules, names, or timelines; `experience` for what happened. Use `kva`, `status`, `work_id` on the hit. Pages with `kva`/`status` of `terminated` / `deprecated` / `superseded` are excluded by default; they appear only with `kva:terminated` (or `--include-exits`). Use them only to explain a dead frame.
8. **Read** 1–3 top pages (full body + frontmatter), including a spine or work hub when it ranks.
9. **Expand** via authoritative `relates_to` (`path` + `kind`) on the hit or page. Body `## Related` is only a mirror. `atlas graph neighbours <page> --root <root> --json` gives the same `relates_to` expansion as structured JSON (direction, kind and hop per edge); see `references/graph.md`.
10. **Never** treat `staging/` as an answer source.
11. **Answer** from claims on those pages, citing paths. If nothing relevant → honest **gap**. After the one rewrite search, stop. A grep spiral is not allowed.

## Preferred engine

A consuming project can choose the engine recall uses when no `--engine` is
given, and Atlas creates and refreshes its index automatically. There is no
daemon and no file watcher.

**Configuration** (values `grep`, `bm25`, `nanograph`):

- store row in the project's `atlas-mesh.json`:
  `{"id": "...", "path": "...", "recall": {"engine": "bm25"}}`;
- project default, top level of the same file: `"recall": {"engine": "bm25"}`;
- environment: `ATLAS_RECALL_ENGINE=bm25`;
- command: `atlas recall run "<q>" --engine bm25`.

Unknown keys inside `recall` or other values are rejected with an error that
names the file, the store id (or "project default") and the allowed values;
`recall run` exits 2. Mesh files without `recall` behave exactly as before.
Use `atlas index set` (below) to write the entry; editing `atlas-mesh.json`
by hand is possible but not needed.

**Precedence**, highest first: `--engine` (`cli`) > `ATLAS_RECALL_ENGINE`
(`env`) > store row `recall.engine` (`store`, the row matched by the index
location's mesh resolution) > top-level `recall.engine` (`project`) >
built-in default (`default`: SCHEMA `query.search_engine` when it is `bm25`,
else `grep`). A standalone store (no matching mesh row) skips the two mesh
levels. Recall payloads report `engine_requested`, `engine_source`,
`engine_used`, `driver_used` and, when something was substituted,
`driver_note`. `atlas index show [--root R] [--json]` prints the resolved
preference, its source, the effective engine after fallback, the index
directory and its freshness, without building anything.

**Auto-create and refresh.** `bm25` uses the `fts5` index and `nanograph`
the `nanograph` index under `.atlas/indexes/<driver-type>/<atlas-id>/`;
`grep` has no index. Whenever the engine comes from `cli`, `env`, `store` or
`project`, recall checks the content-based corpus digest (sorted relative
paths plus the sha256 of each page, plus the projection inputs: the bytes of
`SCHEMA.json` / `CONTRACT.json`, the `schema.d/*.json` overlays (the same
list overlay merging reads, receipts excluded; store scope hashes a symlinked `schema.d`,
symlinked overlays and a symlinked contract file from the bytes of
their targets, while mesh scope skips those symlinks with a warning and does not open or hash the target) and the projection version, so a schema-only change such as SCHEMA 1.0 to 2.0 or a
new relation vocabulary also makes the index stale; the path/size/mtime
fingerprint is only a pre-check that can rule an index stale, never fresh) and, for nanograph,
the binary version. If the index is missing or stale it
builds a new generation and publishes it before answering. Unchanged content
means no rebuild. `atlas compile` / `validate` (not `--dry-run`) and
`atlas index build` also refresh the preferred index after a
successful run and report `preferred_index_refreshed` or
`preferred_index_fresh` (driver and generation) as info. A build failure is
the warning `preferred_index_failed`; exit codes never change because of
index work. If `/.atlas/indexes/` cannot be added to `info/exclude`
(unreadable or unwritable file, failing `git rev-parse`), the build still
happens and the warning `atlas_indexes_ignore_failed` says to add the line
yourself; it is never treated as already ignored.

**Atomic publish and lock.** A builder takes `<index-dir>/.lock`
(`O_CREAT|O_EXCL`, JSON with a per-build `owner` token, pid, host and
`created_at`). A lock older than ten minutes, or whose pid is no longer
running on the same host, is stale: the next builder renames it aside
(`.lock.stale-<owner>-<random>`, atomic) and creates its own. Only the owner
releases a lock. Takeover (re-check, rename aside, create) and release
(re-check, remove) both run under a short-lived `.lock.takeover` guard
(`O_EXCL`, with its own owner token, removed only by its creator; a guard
older than 30 s is abandoned and broken safely). A takeover therefore cannot
land between a release's ownership check and its removal, and a legitimate
owner's lock is never moved aside, even briefly. The final ownership
check, the pointer replace and pruning run in one short critical section
under that same guard (`OwnedLock.owned_critical_section`), so no takeover
or release can land between the check and the write; the build itself
stays outside it, and pruned generations are only renamed to `.tmp-*`
inside it and deleted afterwards. A builder that lost the lock publishes
nothing, deletes its new generation and reports `lock_lost`, and readers
keep the new owner's pointer. `atlas-mesh.json` writers re-check ownership
and replace the file under the guard of `atlas-mesh.json.lock` the same
way; one that lost the lock exits 2 without writing. A builder that finds its lock taken over at
release leaves it in place and adds a `lock_lost` debug warning to the
build result. The builder writes into a
`.tmp-<generation>` sibling, fsyncs, renames it into place with
`os.replace`, then replaces the pointer (`current.json`) atomically. Readers
resolve the pointer once, so they never see a half-built generation; leftover
`.tmp-*` entries are ignored and removed by the next builder. Pruning keeps
the pointer's generation plus one other: the previous pointer's generation
when it still exists, else the newest (fts5 and nanograph alike).
A reader that finds the lock held waits up to five seconds for a fresh
generation; if none appears, bm25 answers from a temporary index and
nanograph falls back to bm25, both with a `driver_note`. When the index
location cannot be written (read-only file system, permissions, unsafe
path), bm25 also answers from a temporary index (`ephemeral: true`) and says
why in `driver_note`.

**Legacy.** The deprecated `.atlas-index/` location is read only when the new
`.atlas/indexes/<driver-type>/<atlas-id>/` location holds no index at all (no
`current.json` pointer and no published generation; for tgrep, no index
directory). Then a fresh legacy index is read in place with a
`legacy_index_location` warning. Once any new-location index exists, a stale
one (corpus digest, nanograph version or index format changed) is rebuilt at
the new location and legacy is not read, even when it is fresh. A stale
legacy index is never refreshed: Atlas builds the new location and never
writes to `.atlas-index/`. The rule is the same for fts5, nanograph and tgrep.

**Fallback** never fails recall: nanograph -> bm25 -> grep, bm25 -> grep
(FTS5 unavailable). Availability comes from the driver overlay (nanograph:
macOS arm64, binary present, version 1.3.0 or later); no index is built for
an unavailable driver. Example: `driver_note: "preferred engine nanograph
unavailable: unavailable on linux-x86_64; used bm25"`, exit 0.

**Stores with their own recall profile** (SCHEMA 2.0, recall enabled). The
profile is authored in the store and versioned with it, so it is the stronger
contract; mesh and environment preferences are a per-consumer convenience.
The profile therefore stays authoritative for the rank pipeline:

- preference `bm25`: no-op for ranking (the profile's `sqlite-fts5` is BM25
  already); its index lives in the new location and is auto-refreshed by
  recall and compile with the same freshness and atomic-publish code;
- preference `nanograph` or `grep` from `store`, `project` or `env`: not
  applied; the payload carries info `preferred_engine_ignored` ("store recall
  profile <name> is authoritative; preferred engine <x> from <source> not
  applied") and no nanograph index is built;
- explicit `--engine`: still a conflict (exit 2); the error points to
  `--profile` and explains that preferences are ignored on profile stores.

## Managing engines and indexes: `atlas index`

`atlas index` manages the preferred engine and its indexes so nobody needs to
edit `atlas-mesh.json` by hand (hand-editing still works). "Engine" is
`grep`, `bm25` or `nanograph`; the file key stays `recall.engine`. Every
command takes `--root` (default: the current directory). A `--root` that
does not exist or is not a directory exits 2 with `code: root_not_found`
before any store matching, and nothing is written. A mounted store, or any
existing directory inside one, selects that store and its mesh project; any
other directory uses the nearest `atlas-mesh.json` at or above it. A
directory that is neither a store nor inside a mounted store (a project
root, a project subdirectory, a plain directory) is never given an invented
store id: verbs that need one store exit 2 instead (see `show` and `build`).

```text
atlas index set bm25                                # store at --root (its atlas-mesh.json row)
atlas index set nanograph --store github.com/acme/notes
atlas index set bm25 --default                      # default for all Atlases in the project
atlas index set bm25 --default --build              # ...and build for the stores that inherit it
atlas index unset [--store <atlas-id> | --default]
atlas index show [--store <atlas-id>]
atlas index status
atlas index build [--store <atlas-id> | --all] [--force]
```

- **`set <engine>`** writes `recall.engine` on one store row (`--store`, or
  the store at `--root`) or at the top level (`--default`). `--store`
  accepts any spelling that normalises to the row id (for example
  `https://github.com/acme/notes.git`). `--store` with `--default`, an
  unknown engine or an unknown store id (the error lists the known ids) exit
  2. Without an `atlas-mesh.json`, or for a standalone store with no row, the
  command exits 2 and suggests `atlas mount`; it never creates a mesh file.
  When the engine is unavailable on this machine the setting is still
  written (exit 0) with the warning `engine_unavailable_here`, for example
  "nanograph unavailable on linux-x86_64; recall here will fall back to
  bm25" (stderr outside `--json`). `--build` then builds or refreshes the
  index now, with the same code recall uses: for the target store, or with
  `--default` for every row without its own value. Each store reports its
  effective engine, index directory and generation, "no index needed" (grep
  or a grep fallback) or "skipped: store not mounted".
- **`unset`** removes `recall.engine` (and an empty `recall` object); a
  second run reports `changed: false`. Index files stay; delete
  `.atlas/indexes/<type>/<atlas-id>/` by hand if you no longer want them.
- **`show`** lists the configured value per level (`ATLAS_RECALL_ENGINE`,
  store row, project default, built-in default), the winning engine and its
  source, the effective engine after fallback and why, whether a store
  recall profile makes the preference ignored (with the profile name), and
  the project-relative index directory with its freshness: `fresh`,
  `stale`, `missing` or `legacy-only` (decided by the content digest), plus
  the generation id and a corpus digest prefix, and `ignore: ok|missing|failed`
  (with the reason; `n/a` outside git): whether git actually ignores
  `.atlas/indexes/` (`git check-ignore`). `show` is per store: `--store`,
  or the store at (or containing) `--root`. At a project root or another
  directory that is not a store, without `--store`, it exits 2 with
  `code: store_required`, for example "<root> is a project root, not a
  store; pass --store <atlas-id> (known: a, b) or run `atlas index status`
  for every store", plus a `hint` and, in `--json`, `known_ids`. When the
  mesh has exactly one store row, that row is shown instead, with
  `selected: only_mesh_row` (a `note:` line in text mode). Without any
  `atlas-mesh.json` and not a store, it exits 2 with `code: not_a_store`
  and suggests `atlas mount`. A store whose contract cannot be read
  reports `ok: false` with the `error` (exit 1); `ok` is never `true`
  alongside an `error`.
- **`status`** shows every row of the project's `atlas-mesh.json` and the
  project default: id, mounted, configured engine and source, effective
  engine, freshness and index directory (one row for a standalone store),
  plus the project's `ignore` status as in `show`. It does so from the
  project root, any subdirectory or inside a mounted store; inside a store,
  `current_store` (and `current: true` on its row, a `current store:` line
  in text mode) names that store. `ok` is `false` (exit 1) when any row has
  an `error`. Without an `atlas-mesh.json`, a directory that is not a store
  exits 2 with `code: not_a_store` and the `atlas mount` hint.
- **`build`** builds or refreshes the index for the effective engine of the
  store at (or containing) `--root`, of `--store <atlas-id>`, or of every
  mounted row with `--all` (unmounted rows are skipped). At a project root
  without `--store`/`--all` it resolves the store as `show` does: the only
  row of a one-store mesh, otherwise exit 2 with `code: store_required` and
  a hint for `--store`/`--all`. It rebuilds only when stale unless
  `--force` is given. Profile stores build the profile's `fts5` index. Exit
  0 when every build succeeded or was not needed; exit 1 when any failed
  (the others are still attempted and each failure is reported).

Writing commands report `changed`, `target` (store id or `default`),
`previous`, `value` and `mesh_file` (project-relative). Writes change only
the target's `recall` key: other keys, row order, indentation and the
trailing newline are kept, an unchanged value leaves the file untouched, and
the new file is written to a temporary sibling, fsynced and renamed into
place. A file that is not valid JSON or does not validate is refused (exit
2, nothing written); the one exception is that `set`/`unset` may repair an
invalid `recall` block on the target itself.

**Locking.** Every `atlas-mesh.json` write (`index set`/`unset`, `mount`'s
row upsert, store removal) takes `<project>/atlas-mesh.json.lock`, the same
owner-token lock index builders use (`core/owned_lock.py`), re-reads the file
under it, applies the change, validates, writes atomically and releases, so
concurrent writers never lose each other's changes. A lock older than 60
seconds, or whose process is gone on this host, is taken over. A writer
waits up to 10 seconds for a held lock and then exits 2 naming the lock
file, without writing. The lock and the `.atlas-mesh.json.*.tmp` temp
files are short-lived; in a git work tree the writer also adds
`/atlas-mesh.json.lock*` and `/.atlas-mesh.json.*.tmp` (anchored at the
project directory) to `info/exclude` so a leftover never gets committed.
When those rules cannot be added (an unreadable or unwritable
`info/exclude`, `info` that is not a directory, or a failing `git
rev-parse`), every mesh writer (`index set`/`unset`, `mount`, `store init`
/ `rehost` and their store removal) still writes the mesh and keeps its exit
code, and adds the warning item `atlas_mesh_lock_ignore_failed` to the
payload's `warnings`: `could not add atlas-mesh.json.lock* and temp-file
rules to <path>: <reason>; add them to .gitignore or info/exclude
yourself` (one stderr line outside `--json`).

**Deprecated:** `atlas recall index build` still works for 0.14.x as an alias
of `atlas index build` for the store at `--root`, with the same payload plus
a `deprecated_command` warning (and a stderr line outside `--json`).

## Exit receipt

```text
skill: atlas
skill_path: …
path: recall
root: …
recall_cmd: atlas recall run "…" --root …
hits_used: <paths>
pages_read: <paths>
stopped_at: frame | schema | gist | memory | recall_hit | gap
opened_page_reason: <present only when a page is opened>
remember: no
compile: n/a
```

`stopped_at: recall_hit` means the answer came from ordinary search rather than
the progressive memory walk. `stopped_at: gap` means an honest gap — nothing
relevant was found. `stopped_at: frame` is the shipped `SCHEMA.json` name;
`stopped_at: schema` is the current `CONTRACT.json` name. A hub is never a stop
level in this walk.

For a structural question, `recall_cmd` records the `atlas graph …` command that ran.

Claiming “checked the Atlas” without `recall_cmd` ⇒ incomplete Exit.

## Non-goals

- Writing or compiling the store (use **remember** / **work**).
- OKF format rules (use skill **okf**).
- Treating compile `--type` as recall discovery.
