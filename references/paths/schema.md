---
name: atlas/paths/schema
description: Create, install, validate, or uninstall SCHEMA overlays. CLI is the only writer. Load before any schema create/update/install work.
path_id: schema
---

# Path: schema

## When

Any of:

- New Atlas root needs its first `SCHEMA.json`
- A **project** needs a bespoke type or extra SCHEMA keys before a skill exists
- A **skill** ships types (`protostar`, `kva`, …) into its own store or a host Atlas
- An overlay must be upgraded or removed
- Compile is red on overlay / core-clash / undeclared root writes

Not for writing knowledge pages (use **remember** / **work**). Not for OKF format rules (use skill **okf**).

## Enter (required — Atlas `activation_card: on`)

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: schema
path_module: references/paths/schema.md
intent: <one line>
root: <atlas store root>
```

Then **read this file**. Missing card or unloaded module ⇒ incomplete Enter.

Other paths may call `atlas compile` as a tool. They must not hand-edit `SCHEMA.json` or `schema.d/`.

## Choose the verb

| Situation | Verb |
|-----------|------|
| Empty folder, no `SCHEMA.json` | `init` then, if this is a skill store, `schema install` |
| Project idea, not a skill yet | `schema new <id>` then `schema install` a local overlay file when types exist |
| Skill contribution into a store | `schema install <source>` |
| Overlay required-keys changed | `schema install … --force` |
| Remove a contribution | `schema uninstall <id>` |
| Check merge / clashes only | `compile` |
| SCHEMA 1.0 → 2.0 envelope (does not enable recall) | `schema upgrade` then path `configure` |

Never skip compile after a write.

## Hard rules

1. **CLI is the only writer** of `SCHEMA.json` and `schema.d/`. Do not open those files in an editor and save. If `python3 <atlas-skill>/scripts/atlas.py` is missing, **stop** (fail-closed).
2. **Init writes core only.** No skill namespaces (`kva`, …) in the born SCHEMA.
3. **Overlays add types.** They must not set `atlas_id`, `compile`, `structure`, `schema_version`, or redeclare core `templates.by_type` entries (`work`, `document`, `experience`, …).
4. **Author the overlay outside the store**, then install. Legal places to *compose* JSON: a skill `contributions/<id>/SCHEMA.overlay.json`, or a temp file you pass to `schema install`. Illegal: editing `schema.d/<id>.json` in place.
5. **Receipt is evidence.** Compile fails if a receipt lists a path that is not under `schema.d/` and not under `claimed_folders`.
6. **Knowledge folders stay free layout.** Do not `schema new --claim` a folder just because pages live there.

## Procedure

### 0. Resolve root

Same as query. Always pass `--root`. Omitting `--root` uses cwd, not the skill mount.

### 1. Birth a store

```bash
python3 <atlas-skill>/scripts/atlas.py init --root <root>
```

Refuses to overwrite without `--force`. Then compile.

Skill-owned process memory: immediately install that skill’s overlay (step 3). Do not copy keys into SCHEMA.json.

### 2. Project overlay (no skill yet)

```bash
python3 <atlas-skill>/scripts/atlas.py schema new <kebab-id> --root <root> [--claim <folder>]
```

- `<kebab-id>` like `experiments` or `ignite-2026` (not `Not_Kebab`).
- `--claim` is optional and repeatable. Only claim folders this overlay’s CLI writes will own.
- This writes `schema.d/<id>.json` + `.receipt.json`. It does **not** yet add types.

To add types: author an overlay file (shape below) with the same `contribution_id`, then `schema install <file> --root <root>` (`--force` if the overlay already exists).

### 3. Install a contribution

Source is one of:

- a file `SCHEMA.overlay.json`
- a directory containing that file
- `contributions/<id>/` in a skill package (overlay + optional `templates/<newtype>.md`)

```bash
python3 <atlas-skill>/scripts/atlas.py schema install <source> --root <root> [--force]
```

`--force` is required when this overlay’s `templates.by_type.*.frontmatter.required` changed. Without it, install exits 2.

Install copies **new-type** templates only. It will not overwrite core `templates/work.md`.

### 4. Uninstall

```bash
python3 <atlas-skill>/scripts/atlas.py schema uninstall <id> --root <root>
```

Deletes `schema.d/<id>.json` and paths on that overlay’s receipt (overlay + templates the CLI copied). Does **not** delete pages the agent authored later. Compile may still see those pages; unknown `type` stays legal under OKF. If they used types that lived only on the overlay, the CLI prints a warning.

### 5. Compile (always)

```bash
python3 <atlas-skill>/scripts/atlas.py compile --root <root>
```

Effective SCHEMA = core `SCHEMA.json` ∪ `schema.d/*.json`.

| Issue id | Meaning | Exit |
|----------|---------|------|
| `overlay_core_clash` | Overlay set a forbidden core key | 2 |
| `overlay_core_type` | Overlay redeclared a core `by_type` | 2 |
| `overlay_key_clash` | Two overlays claim the same extra key or type | 2 |
| `overlay_undeclared_root` | Receipt lists a path outside claimed prefixes / `schema.d/` | 2 |
| `overlay_receipt` | Installed overlay has no receipt | 2 |
| `overlay_json` / `overlay_id` | Unreadable overlay or id ≠ filename | 2 |

Exit 2 → fix via **schema** verbs, not a text edit. Then compile again. Do not claim the store is healthy.

### 6. log.md

Append one bullet only when schema layout changed (init, first overlay, uninstall). Not for every type tweak.

## Overlay file to author (outside the store)

```json
{
  "contribution_id": "discuss",
  "claimed_folders": ["protostars"],
  "templates": {
    "by_type": {
      "protostar": {
        "file": "templates/protostar.md",
        "frontmatter": {
          "required": ["type", "title", "created"],
          "recommended": ["kva", "status"]
        },
        "sections": { "required": [], "recommended": ["Pending", "Origin"] }
      }
    }
  }
}
```

Skill package layout:

```text
contributions/<id>/
  SCHEMA.overlay.json
  templates/<newtype>.md    # optional; copied on install for new types only
```

Extra root keys (for example `kva`) are allowed if they are **not** already on core SCHEMA and **not** used by another overlay.

## Worked sequences

**New project Atlas, later a custom type**

1. `init --root <root>`
2. `schema new my-idea --root <root>`
3. Write `SCHEMA.overlay.json` beside the skill or in tmp (`contribution_id: my-idea`, new types only)
4. `schema install <that-file> --root <root>`
5. `compile --root <root>`

**Skill store (discuss, autogenesis, …)**

1. `init --root <skill>/references/atlas` if missing
2. `schema install <skill>/contributions/<id> --root <skill>/references/atlas`
3. `compile`

**Host Atlas receiving a skill**

Same as skill store, but `--root` is the **host**. Do not dump skill folders at the host root; only claimed prefixes plus `schema.d/`.

## Exit receipt

```text
skill: atlas
path: schema
root: …
verb: init | schema new | schema install | schema uninstall | compile
compile: exit N
```

Incomplete if the verb wrote SCHEMA by hand, CLI was missing and you continued, or compile stayed red.

## Non-goals

- Hand-edit `SCHEMA.json` / `schema.d/`
- Sandbox overlays that skip compile
- A catalog skill named schema
- Migrating live in-place SCHEMA keys (`kva`) — separate work
- Changing OKF reserved names or closing the type enum
