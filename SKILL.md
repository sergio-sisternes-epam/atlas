---
name: atlas
description: Use for durable OKF v0.2 knowledge stores - skill process memory, decisions, work hubs, and project knowledge graphs. Triggers on atlas, atlas search, atlas compile, skill memory, work hub, remember knowledge, query atlas, knowledge substrate, refresh landscape, update competitors, symbiont, who should we partner with, schema overlay, atlas init, schema install. Load a path module (query, remember, work, landscape, schema) before acting. Format rules remain in the skill named okf. Successor to okf-wiki operational layer.
---

# Atlas

Durable, modular **OKF v0.2** knowledge substrate for skills and projects.

**Format authority:** skill **`okf`**. Atlas does not re-implement OKF rules.

**Default store:** the canonical process-memory Atlas is the separate repo `sergio-sisternes-epam/atlas-atlas`. In this package checkout, `references/atlas/` is a git submodule of that store. Author memory pages in atlas-atlas (or the live Grok working copy), not as ordinary files of the atlas package.

## Activation card (required)

Before formal query or any store mutation, emit:

```text
skill: atlas
skill_path: <resolved Atlas skill directory>
mode: run | discussion
subject: atlas | <project>
path: query | remember | work | landscape | schema
path_module: references/paths/<path>.md
intent: <one line>
root: <atlas root path>
```

Then read `path_module` from the resolved Atlas skill directory and follow it.
Do not run from this router alone.

## Path registry (load before execute)

| path_id | When | Module |
|---------|------|--------|
| **query** | Find / answer from an Atlas | `references/paths/query.md` |
| **remember** | Write experiences, decisions, lessons, recipes; compile green | `references/paths/remember.md` |
| **work** | Open, update, or close `work_id` hubs | `references/paths/work.md` |
| **landscape** | On-demand competitor + symbiont research; write comparison memory | `references/paths/landscape.md` |
| **schema** | Init, overlay install/new/uninstall; compile merge | `references/paths/schema.md` |

Paths are **not** separate catalog skills. CLI verbs (`search`, `compile`, ...)
are tools used inside paths.

## Hard rules

1. **Formal lookup = path `query` + `atlas search`** - B17 card `path: query`, load `references/paths/query.md`, then the CLI. Do not merge those names. Unbounded whole-tree grep/rg/find is not path query. On synthesis or a mention-only hit list, rewrite once from `glossary.md` Search aliases and prefer spine / work-hub pages.
2. **`staging/` never answers** - compile hard-fails if staging is non-empty.
3. **Writes end on compile green** - `atlas compile --root <root>` exit 0 before claiming memory stored. Compile checks SCHEMA shape, required frontmatter, and required links - not markdown headings. `index_md_present` and `index_md_listing` are warnings (`exit 1`), never critical. Listing checks concept `.md` pages and child folders with an index; media files are ignored. New page-contract misses are warnings until promoted.
4. **`relates_to` / `kind` are authoritative** - body `## Related` is optional mirror.
5. **Work cluster** - pages with a `work_id` link `work/<work_id>.md` with `kind: implements`.
6. **`log.md`** - append only for structural store changes (not every experience).
7. **Format-only questions** -> skill **`okf`**.
8. **Interim:** new process memory and knowledge ops for this substrate -> **Atlas paths**, not okf-wiki (until migration work completes).
9. **Wrong-frame correction** - if the user explicitly kills a comparison or thesis, activate the optional companion skill **discuss** and use its `terminate` path (recipe `references/recipes/terminate-wrong-path.md`). If `discuss` is unavailable, stop and tell the user that this path requires the companion skill; do not keep writing the dead frame.
10. **Thoughtful current-theory remember** - writing `lesson`, live `decision`, or `recipe` requires this skill's remember card and a designed inventory (path, type, one-line claim, source URIs) produced by the agent before write. Human request and approval are **not** default gates. If the human asks for review on an important persist, stop after the inventory and wait. Recipe: `references/recipes/gated-memory-building.md`. Decision (atlas-atlas store, not this package): `decisions/atlas-memory-layers.md`.
11. **SCHEMA mutations = path `schema` + CLI** - load `references/paths/schema.md`. Do not hand-edit `SCHEMA.json` or `schema.d/`.

## CLI surface

Resolve `<atlas-skill>` to this skill's installed `skill_path`; do not resolve
the following commands relative to the consumer project.

```text
python3 <atlas-skill>/scripts/atlas.py init --root <atlas> [--force]
python3 <atlas-skill>/scripts/atlas.py compile|validate --root <atlas> [--type <type>] [--path <prefix>]
python3 <atlas-skill>/scripts/atlas.py search "..." --root <atlas> [--engine grep|bm25] [--include-exits]
                       # query tokens: type: kva: status: work_id: path:
python3 <atlas-skill>/scripts/atlas.py id <pointer>
python3 <atlas-skill>/scripts/atlas.py auth [--host github.com] [--ssh]
python3 <atlas-skill>/scripts/atlas.py mount <source> [--ref <branch>] [--target <path>] [--ssh]
python3 <atlas-skill>/scripts/atlas.py resolve <pointer>
python3 <atlas-skill>/scripts/atlas.py migrate <source> --root <atlas>
python3 <atlas-skill>/scripts/atlas.py promote <staging-file> --to <path> [--type ...] --root <atlas>
python3 <atlas-skill>/scripts/atlas.py schema new <id> --root <atlas> [--claim <folder>]
python3 <atlas-skill>/scripts/atlas.py schema install <source> --root <atlas> [--force]
python3 <atlas-skill>/scripts/atlas.py schema uninstall <id> --root <atlas>
```

Search engine: SCHEMA `query.search_engine` (`grep` pilot default; `bm25` when index exists).

## Core contract (summary)

| Topic | Rule |
|-------|------|
| Structure | Free layout; mandatory `SCHEMA.json`; short-lived `staging/`; `index.md` / `log.md` per OKF |
| Types | `experience`, `decision`, `work`, `lesson`, `recipe`, `document`, `protostar` (recommended, not closed) |
| Origin / sensitivity | Recommended frontmatter: `origin` (internal \| third-party \| user \| derived), `sensitivity` (public \| internal \| restricted) |
| Relations | `relates_to: [{path, kind}]` - kinds: follows, records, supersedes, implements, derived_from, related |
| Composition | Optional mesh; consolidated in compile |
| Provenance | Optional `sources` profile on extracted pages |

## Skill relationship

| Skill | Role |
|-------|------|
| `okf` | Format authority |
| `okf-wiki` | Legacy only - **do not use for new process memory**; prefer Atlas paths until migration |
| `autogenesis` | May use Atlas as process memory |
| `construct` | Adversarial / happy-path evaluation |
| `discuss` | KVA discussion fabric; path `terminate` owns wrong-frame exit ramps |

## Non-goals

- Replacing `okf`
- Phone-home telemetry
- Auto-authoring claims without an agent
- BM25 / live okf-wiki migration (separate work `atlas-bm25-and-live-migration-v1`)

## Progressive disclosure

Procedures live only under `references/paths/`. Load one path per intent (query, remember, work, landscape, schema). SCHEMA and templates under `references/`.
