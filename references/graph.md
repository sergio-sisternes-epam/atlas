# atlas graph — structural lookups

`atlas graph` answers structural questions over a store's authoritative
`relates_to` graph and top-level frontmatter: which pages have
`field=value`, what links to a page and how, a bounded neighbourhood, and a
deterministic export. It is a separate command from `atlas recall run`
(which ranks text) but reads the same projection.

All verbs are read-only and dependency-free. They never write to the store
and never build or publish a recall index. The one exception is the opt-in
`neighbours --driver nanograph`, which may build a nanograph index under
`.atlas-index/nanograph/` and nowhere else; see `references/drivers.md`.

## Data source

- Works on every store: `SCHEMA.json` or `CONTRACT.json`, schema 1.0 or
  2.0, recall on or off. No index is required.
- When a published recall generation exists and its cheap fingerprint
  matches the tree, pages come from it (`fast_path: true`, `generation`
  set). Otherwise the current tree is projected in memory
  (`fast_path: false`, `generation: null`).
- Excluded exactly as recall excludes them: `log.md` pages (role `log`),
  the staging directory, `templates/`, `.atlas-index/`, `schema.d/` and
  `mesh/`.
- A projection error (for example invalid SCHEMA 2.0 YAML) exits 2 with the
  message. With `--allow-partial` the command exits 1 instead, with
  `complete: false` and an `omitted` list of `{path, reason}`.

Every JSON payload carries `ok`, `root`, `verb`, `generation`,
`corpus_digest`, `fast_path`, `complete` and `count`. Usage errors (unknown
page, malformed `--where`, `--hops` above 3, `--out` inside the store) exit
2 with `ok: false` and `error`.

## Exit-state rule

As in recall, a page whose `kva` or `status` is `terminated`, `deprecated`
or `superseded` is hidden unless `--include-exits` is passed, or a
`--where kva=<exit>` / `--where status=<exit>` explicitly asks for an exit
value. An edge touching a hidden page (at either end that exists) is hidden
too. Exports always include every page.

## Verbs

### nodes

```text
atlas graph nodes --root R [--where field=value]... [--path PREFIX] [--include-exits] [--limit N] [--json]
```

`--where` matches any top-level scalar frontmatter field on normalised text:
booleans as `true`/`false`, numbers via `str()`, strings stripped. Several
`--where` options are ANDed. A list-valued field matches when any element
equals the value. A missing field never matches. `--where` without `=`
exits 2. `--limit` cuts the sorted list and sets `truncated: true`.

Node record:

```json
{"path": "stars/p1.md", "type": "protostar", "title": "Star one",
 "kva": "forming", "growth": true,
 "fields": {"created": "2026-09-09", "growth": "true", "kva": "forming", "title": "Star one", "type": "protostar"}}
```

`kva`, `status`, `work_id` and `growth` appear only when set. `fields` holds
the top-level scalar frontmatter as normalised text; lists and maps
(`relates_to`, `sources`, tags) are left out, so the record reads the same
on schema 1.0 and 2.0 stores.

### edges

```text
atlas graph edges --root R (--from PAGE | --to PAGE | --all) [--kind K]... [--include-exits] [--json]
```

Edges keep authored direction: the page holding `relates_to` is `from`.
PAGE arguments are store-relative paths; a leading `./` is normalised on
both arguments and targets. `--from` must name a page in the store; `--to`
may name any target, including a missing one. `--from` and `--to` may be
combined.

```json
{"from": "notes/child-b.md", "to": "notes/missing.md", "kind": "related", "resolved": false}
{"from": "notes/child-b.md", "to": "atlas://github.com/example/okf-atlas/lessons/remote.md",
 "kind": "derived_from", "resolved": false, "external": true}
```

`resolved` is true when the target is an eligible page in the store.
`external: true` marks `atlas://` targets. Unresolved edges are always
reported, never dropped.

### neighbours

```text
atlas graph neighbours PAGE --root R [--kind K]... [--direction in|out|both] [--hops 1..3]
                       [--where field=value]... [--max-nodes N] [--max-edges N] [--include-exits] [--json]
```

Breadth-first and cycle-safe from the seed PAGE (unknown PAGE exits 2).
Defaults: `--direction both`, `--hops 1` (above 3 exits 2), 200 nodes, 500
edges; `truncated: true` when a cap bites.

- **Direction** is relative to the traversal step: `out` follows edges the
  current page authored; `in` follows edges other pages authored towards
  it. Each edge record still keeps authored `from` and `to`.
- `--kind` restricts which edges are traversed.
- `--where` filters the returned `nodes` only. Traversal passes through
  non-matching pages, so a 2-hop match is reached through a non-matching
  middle page. `edges` lists every traversed edge.
- The seed is reported as `seed` and never listed in `nodes`. Each page
  and each authored edge appears once, at the smallest hop.
- Only resolved page-to-page edges are traversed; use `edges` to see
  unresolved and external targets.

Node records add `hop`; edge records are
`{"from", "to", "kind", "direction": "in"|"out", "hop"}`.

`--driver native|nanograph` (default `native`) picks the traversal driver.
Results are identical; the payload reports `driver_used` (`native-graph`
or `nanograph`) and, when nanograph was asked for but could not run,
`driver_note` (for example `nanograph unavailable on linux-x86_64`) with
exit 0. See `references/drivers.md`.

### drivers

```text
atlas graph drivers [--root R] [--json]
```

Lists the driver registry, each driver's capabilities and platforms, the
platform matrix, the current platform and each driver's detection result.

### export

```text
atlas graph export --root R --format json|nanograph --out DIR [--allow-partial] [--json]
```

DIR is created when missing and must be outside the store root (otherwise
exit 2). Output is byte-identical across runs on the same tree; there are
no timestamps.

- `json` writes `DIR/graph.json`:
  `{"version": 1, "corpus_digest", "nodes": [node record + "description"], "edges": [edge records, unresolved included]}`.
- `nanograph` writes `DIR/schema.pg`, `DIR/seed.jsonl` and
  `DIR/export-receipt.json`, targeting the nanograph v1.3.0 schema and
  JSONL seed grammar.

#### nanograph mapping

| Atlas | nanograph |
|-------|-----------|
| page | `node Page` — `slug: String @key` (store-relative path), `title: String @index`, `description: String?`, `body: String`, `text: String @index` (title, description and body joined by newlines), `role: String`, `growth: Bool?`, `consolidation: Bool?`, then `String?` for `type, kva, status, work_id, star_kind, kva_role, origin, sensitivity`, in that order |
| `atlas://` target | `node External { slug: String @key }` |
| relation kind | `edge <Name>: Page -> Page`, one per kind present plus the effective schema's `relations.recommended_kinds`; Name is PascalCase (`kva_terminate` → `KvaTerminate`, `derived_from` → `DerivedFrom`) |
| kind with an `atlas://` target | additional `edge <Name>External: Page -> External` |

Edge types are sorted by name. There are no `Vector` fields and no `@embed`.
`seed.jsonl` holds `{"type":"Page","data":{...}}` lines sorted by slug, then
`External` lines sorted by slug, then `{"edge":Name,"from":slug,"to":slug}`
lines sorted by (edge, from, to); each line is compact JSON with sorted keys,
and unset optional properties are `null`. Unresolved non-external edges are
not seeded; `export-receipt.json` lists them under `unresolved`, with
per-kind edge counts, page count, `corpus_digest`, `format` and
`nanograph_schema_grammar: "1.3.0"`.

## Determinism

Nodes are sorted by (hop, path) and edges by (hop, from, to, kind); verbs
without hops sort by path and (from, to, kind). JSON output uses sorted
keys. Human output is one compact line per record plus a `# count=...`
footer.
