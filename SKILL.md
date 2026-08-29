---
name: atlas
description: Use for durable OKF v0.2 knowledge stores — skill process memory, decisions, work hubs, and project knowledge graphs. Triggers on atlas, atlas search, atlas compile, skill memory, work hub, remember knowledge, query atlas, knowledge substrate, refresh landscape, update competitors, symbiont, who should we partner with. Load a path module (query, remember, work) before acting. Format rules remain in the skill named okf. Successor to okf-wiki operational layer.
version: 0.8.1
status: active
work_id: 2026-08-27-atlas-search-nav-signals
plan_path: /home/workdir/artifacts/autogenesis-plans/2026-08-23-atlas-agentic-integration-v1.md
activation_card: on
---

# Atlas

Durable, modular **OKF v0.2** knowledge substrate for skills and projects.

**Format authority:** skill **`okf`**. Atlas does not re-implement OKF rules.

**Default store (this skill):** `references/atlas/`

## Activation card (required)

Before formal query or any store mutation, emit:

```text
skill: atlas
skill_path: /home/workdir/.grok/skills/atlas
mode: run | discussion
subject: atlas | <project>
path: query | remember | work | landscape
path_module: references/paths/<path>.md
intent: <one line>
root: <atlas root path>
```

Then **`read_file` the `path_module`** and follow it. Do not run from this router alone.

## Path registry (load before execute)

| path_id | When | Module |
|---------|------|--------|
| **query** | Find / answer from an Atlas | `references/paths/query.md` |
| **remember** | Write experiences, decisions, lessons, recipes; compile green | `references/paths/remember.md` |
| **work** | Open, update, or close `work_id` hubs | `references/paths/work.md` |
| **landscape** | On-demand competitor + symbiont research; write comparison memory | `references/paths/landscape.md` |

Paths are **not** separate catalog skills. CLI verbs (`search`, `compile`, …) are tools used inside paths.

## Hard rules

1. **Formal lookup = path `query` + `atlas search`** — B17 card `path: query`, load `references/paths/query.md`, then the CLI. Do not merge those names. Unbounded whole-tree grep/rg/find is not path query. On synthesis or a mention-only hit list, rewrite once from `glossary.md` Search aliases and prefer spine / work-hub pages.
2. **`staging/` never answers** — compile hard-fails if staging is non-empty.
3. **Writes end on compile green** — `atlas compile --root <root>` exit 0 before claiming memory stored. Compile checks SCHEMA shape, required frontmatter, and required links — not markdown headings. New page-contract misses are warnings (`exit 1`) until promoted.
4. **`relates_to` / `kind` are authoritative** — body `## Related` is optional mirror.
5. **Work cluster** — pages with a `work_id` link `work/<work_id>.md` with `kind: implements`.
6. **`log.md`** — append only for structural store changes (not every experience).
7. **Format-only questions** → skill **`okf`**.
8. **Interim:** new process memory and knowledge ops for this substrate → **Atlas paths**, not okf-wiki (until migration work completes).
9. **Wrong-frame correction** — if the user explicitly kills a comparison or thesis, load catalog skill **discuss** path `terminate` (recipe `references/recipes/terminate-wrong-path.md`). Do not keep writing the dead frame.

## CLI surface

```text
python3 scripts/atlas.py init --root <atlas> [--force]
python3 scripts/atlas.py compile|validate --root <atlas> [--type <type>] [--path <prefix>]
python3 scripts/atlas.py search "…" --root <atlas> [--engine grep|bm25] [--include-exits]
         # query tokens: type: kva: status: work_id: path:
python3 scripts/atlas.py id <pointer>
python3 scripts/atlas.py auth [--host github.com] [--ssh]
python3 scripts/atlas.py mount <source> [--ref <branch>] [--target <path>] [--ssh]
python3 scripts/atlas.py resolve <pointer>
python3 scripts/atlas.py migrate <source> --root <atlas>
python3 scripts/atlas.py promote <staging-file> --to <path> [--type …] --root <atlas>
```

Search engine: SCHEMA `query.search_engine` (`grep` pilot default; `bm25` when index exists).

## Core contract (summary)

| Topic | Rule |
|-------|------|
| Structure | Free layout; mandatory `SCHEMA.json`; short-lived `staging/`; `index.md` / `log.md` per OKF |
| Types | `experience` · `decision` · `work` · `lesson` · `recipe` · `document` · `protostar` (recommended, not closed) |
| Origin / sensitivity | Recommended frontmatter: `origin` (internal \| third-party \| user \| derived), `sensitivity` (public \| internal \| restricted) |
| Relations | `relates_to: [{path, kind}]` — kinds: follows, records, supersedes, implements, derived_from, related |
| Composition | Optional mesh; consolidated in compile |
| Provenance | Optional `sources` profile on extracted pages |

## Skill relationship

| Skill | Role |
|-------|------|
| `okf` | Format authority |
| `okf-wiki` | Legacy only — **do not use for new process memory**; prefer Atlas paths until migration |
| `autogenesis` | May use Atlas as process memory |
| `construct` | Adversarial / happy-path evaluation |
| `discuss` | KVA discussion fabric; path `terminate` owns wrong-frame exit ramps |

## Non-goals

- Replacing `okf`
- Phone-home telemetry
- Auto-authoring claims without an agent
- BM25 / live okf-wiki migration (separate work `atlas-bm25-and-live-migration-v1`)

## Progressive disclosure

Procedures live only under `references/paths/`. Load one path per intent. SCHEMA and templates under `references/`.
