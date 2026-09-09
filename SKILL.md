---
name: atlas
description: Use for durable OKF v0.2 knowledge stores - skill process memory, decisions, work hubs, project knowledge graphs, schema governance, and Atlas CI gates. Triggers on atlas, atlas search, atlas compile, atlas CI, GitHub Actions compile gate, schema overlay, atlas init, schema install, skill memory, work hub, remember knowledge, query atlas, knowledge substrate, refresh landscape, update competitors, symbiont, who should we partner with. Load a path module (mount, init, migrate, query, remember, work, landscape, schema, configure, ci) before acting. Format rules remain in the skill named okf. Successor to okf-wiki operational layer.
version: 0.10.0
activation_card: on
---

# Atlas

Durable, modular **OKF v0.2** knowledge substrate for skills and projects.

**Format authority:** skill **`okf`**. Atlas does not re-implement OKF rules.

**Default store:** `github.com/sergio-sisternes-epam/atlas-atlas`. Load path **`mount`** (`references/paths/mount.md`) before query or persist. That module is not a store. The store mounts at `<git-root>/.atlas/github.com/sergio-sisternes-epam/atlas-atlas`. Do not write into the skill package.

## Activation card (required)

Render every activation card in the assistant response as a fenced Markdown
code block with the `text` info string. The opening and closing fences are part
of the required output contract; an unfenced field list is incomplete.

Before formal query or any store mutation, emit path **mount** first. This skill passes its own store on the card:

```text
skill: atlas
skill_path: <resolved Atlas skill directory>
mode: run | discussion
subject: atlas | <project>
path: mount
path_module: references/paths/mount.md
intent: <one line>
atlas_id: github.com/sergio-sisternes-epam/atlas-atlas
ref: main
root: <set after resolve>
```

Then load `references/paths/mount.md` from the resolved Atlas skill directory
and follow it with those card fields. Missing `atlas_id` or an unloaded module
means Enter is incomplete.

After `root` is set, emit the operational card and load that module:

```text
skill: atlas
skill_path: <resolved Atlas skill directory>
mode: run | discussion
subject: atlas | <project>
path: query | remember | work | landscape | schema | configure | ci
path_module: references/paths/<path>.md
intent: <one line>
root: <atlas store root>
```

Then read `path_module` from the resolved Atlas skill directory and follow it.
Do not run from this router alone.

To **create** a new Atlas, emit path **init** instead of mount. `remote` is required (existing git remote). Never create the host repository:

```text
skill: atlas
skill_path: <resolved Atlas skill directory>
mode: run
subject: atlas | <project>
path: init
path_module: references/paths/init.md
intent: <one line>
remote: <existing git remote URL>
ref: main
root: <set after resolve>
```

If `remote` is missing, ask and stop. Then load `references/paths/init.md`
from the resolved Atlas skill directory.

To **migrate** a skill off `<skill>/references/atlas`, emit path **migrate**.
`atlas_id` is that skill's store (`host/org/repo`):

```text
skill: atlas
skill_path: <resolved Atlas skill directory>
mode: run
subject: <skill>
path: migrate
path_module: references/paths/migrate.md
intent: <one line>
atlas_id: <host/org/repo>
ref: main
```

Then load `references/paths/migrate.md` from the resolved Atlas skill
directory. Missing `atlas_id` means Enter is incomplete. One own store per Run.

## Path registry (load before execute)

| path_id | When | Module |
|---------|------|--------|
| **mount** | Mount-if-missing and resolve `--root` | `references/paths/mount.md` |
| **init** | New Atlas from an existing git remote; never creates the repo | `references/paths/init.md` |
| **migrate** | Move a skill off `references/atlas` onto `.atlas/<id>/` | `references/paths/migrate.md` |
| **query** | Find / answer from an Atlas | `references/paths/query.md` |
| **remember** | Write experiences, decisions, lessons, recipes; compile green | `references/paths/remember.md` |
| **work** | Open, update, or close `work_id` hubs | `references/paths/work.md` |
| **landscape** | On-demand competitor + symbiont research; write comparison memory | `references/paths/landscape.md` |
| **schema** | Init, overlay install/new/uninstall; compile merge | `references/paths/schema.md` |
| **configure** | SCHEMA 2.0 recall inspect, upgrade, explicit profile selection | `references/paths/configure.md` |
| **ci** | Assess, install, or repair CI for a `SCHEMA.json` mount | `references/paths/ci.md` |

Paths are **not** separate catalog skills. CLI verbs (`search`, `compile`, ...)
are tools used inside paths.

## Hard rules

1. **Formal lookup = path `query` + `atlas search`** - B17 card `path: query`, load `references/paths/query.md`, then the CLI. Do not merge those names. Unbounded whole-tree grep/rg/find is not path query. On synthesis or a mention-only hit list, rewrite once from `glossary.md` Search aliases and prefer spine / work-hub pages.
2. **`staging/` never answers** - compile hard-fails if staging is non-empty.
3. **Writes end on compile green** - `atlas compile --root <root>` exit 0 before claiming memory stored. Compile checks SCHEMA shape, required frontmatter, and required links - not markdown headings. An unmounted external `atlas://` reference is a visible, non-blocking warning (`exit 0`) because the dependency may be transient. `index_md_present`, `index_md_listing`, and new page-contract misses remain actionable warnings (`exit 1`) until promoted. Listing checks concept `.md` pages and child folders with an index; media files are ignored.
4. **`relates_to` / `kind` are authoritative** - body `## Related` is optional mirror.
5. **Work cluster** - pages with a `work_id` link `work/<work_id>.md` with `kind: implements`.
6. **`log.md`** - append only for structural store changes (not every experience).
7. **Format-only questions** -> skill **`okf`**.
8. **Interim:** new process memory and knowledge ops for this substrate -> **Atlas paths**, not okf-wiki (until migration work completes).
9. **Wrong-frame correction** - if the user explicitly kills a comparison or thesis, resolve and load the installed companion skill **discuss**, then use its `terminate` path (recipe `references/recipes/terminate-wrong-path.md`). If `discuss` is unavailable, stop and tell the user that this path requires the companion skill; do not infer its procedure or keep writing the dead frame.
10. **Thoughtful current-theory remember** - writing `lesson`, live `decision`, or `recipe` requires this skill's remember card and a designed inventory (path, type, one-line claim, source URIs) produced by the agent before write. Human request and approval are **not** default gates. If the human asks for review on an important persist, stop after the inventory and wait. Recipe: `references/recipes/gated-memory-building.md`. Decision (atlas-atlas store, not this package): `decisions/atlas-memory-layers.md`.
11. **Write-home is the active git repo** - load path `mount` first. Mount-if-missing with no `--target`. Query and persist use `--root` on that mount. No git repository: refuse to persist. Never mount or write at `<skill>/references/atlas`.
12. **SCHEMA mutations = path `schema` + CLI** - load `references/paths/schema.md`. Do not hand-edit `SCHEMA.json` or `schema.d/`.
12a. **Recall policy = path `configure` + CLI** - load `references/paths/configure.md`. Installing a contribution is not activation.
13. **CI layers stay distinct** - path `ci` configures the institutional merge gate on a `SCHEMA.json` mount; `atlas compile` is the CLI tool; path `compile` is separate agent-session discipline. Do not substitute Atlas skill tests for mount CI.

## CLI surface

Resolve `<atlas-skill>` to this skill's installed `skill_path`; do not resolve
the following commands relative to the consumer project.

```text
python3 <atlas-skill>/scripts/atlas.py init --root <atlas> [--force]
python3 <atlas-skill>/scripts/atlas.py compile|validate --root <atlas> [--type <type>] [--path <prefix>]
python3 <atlas-skill>/scripts/atlas.py search "..." --root <atlas> [--engine grep|bm25] [--include-exits] [--profile <id>] [--allow-partial]
                       # query tokens: type: kva: status: work_id: path:
python3 <atlas-skill>/scripts/atlas.py schema upgrade --to 2.0 --root <atlas> [--dry-run|--apply]
python3 <atlas-skill>/scripts/atlas.py recall status|profiles|show|validate|activate|disable --root <atlas>
python3 <atlas-skill>/scripts/atlas.py recall index build --root <atlas>
python3 <atlas-skill>/scripts/atlas.py init --root <atlas> [--schema-version 1.0|2.0]
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

Search engine: grep until recall is enabled. Opt-in default is `atlas:ranked` (published FTS5; query skips YAML projection when the cheap fingerprint matches; product bench beats grep on speed and follow-up reads). `atlas:tgrep` is advanced/limited. See path `query` and path `configure`. Provenance: atlas-atlas lesson `lessons/2026-09-09-opt-in-ranked-after-fast-path.md`.

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

Procedures live only under `references/paths/`. Load one path per intent
(mount, init, migrate, query, remember, work, landscape, schema, configure, ci). SCHEMA
and templates live under `references/`.
