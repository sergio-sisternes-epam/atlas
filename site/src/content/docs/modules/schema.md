---
title: schema
description: Create a store contract, or install, create, upgrade or remove schema overlays, using only the Atlas CLI.
sidebar:
  order: 13
source:
  - references/paths/schema.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/schema.md: 688f768019c69edf9993c99ba408cf816cee0db2
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `schema` module changes the rules of an Atlas store.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
Each store has one *contract file* at its root.
New stores use `CONTRACT.json`. Stores from the shipped 0.13.0-beta releases use `SCHEMA.json`.
A store never has both.
An *overlay* is a JSON file that adds page types or extra keys to the contract.
Overlays live in `schema.d/` inside the store.
The *effective schema* is the core contract file plus every overlay in `schema.d/`.

## When

Use `schema` when:

- a new store needs its first contract file;
- a project needs a bespoke page type or extra keys before a skill exists;
- a skill ships its own types into its own store or into a host store;
- an overlay must be upgraded or removed;
- `compile` is red because of an overlay clash or an undeclared root write.

Do not use `schema` to write knowledge pages. Use [`remember`](/atlas/modules/remember/) or [`work`](/atlas/modules/work/) for that.
Format rules belong to the separate `okf` skill.

## What it does

The agent picks one verb for the situation:

| Situation | Verb |
|-----------|------|
| Empty folder, no contract file | `init`, then `schema install` for a skill store |
| Project idea, no skill yet | `schema new <id>`, then `schema install` a local overlay when types exist |
| Skill contribution into a store | `schema install <source>` |
| Overlay required keys changed | `schema install ... --force` |
| Remove a contribution | `schema uninstall <id>` |
| Check merge and clashes only | `compile` |
| SCHEMA 1.0 to 2.0 envelope (does not enable recall) | `schema upgrade`, then the [`configure`](/atlas/modules/configure/) module |
| Operator asks to change memory severity | `schema memory-rung --set info\|warn\|error` |

The steps are:

1. **Resolve the root.** The agent always passes `--root`. Without it, the CLI uses the current directory, not the mount.
2. **Birth a store.** `init` writes the core contract only. It refuses to overwrite without `--force`.
3. **Create a project overlay.** `schema new <kebab-id>` writes an overlay and its *receipt* (a record of the files the CLI wrote). It adds no types yet. `--claim <folder>` is optional and repeatable. Claim only folders that this overlay's own writes will own.
4. **Install a contribution.** A *contribution* is an overlay file, a directory that holds one, or `contributions/<id>/` in a skill package. Install copies templates for new types only. It never overwrites a core template. If the overlay's required frontmatter changed, install needs `--force`; otherwise it exits 2.
5. **Uninstall.** This deletes the overlay and the files on its receipt. It does not delete pages that the agent wrote later. If those pages used overlay-only types, the CLI prints a warning.
6. **Compile, always.** Exit 2 means an overlay problem, such as a core clash, a key clash between overlays, a missing receipt or an undeclared root path. Fix it with `schema` verbs, not a text edit. Then compile again.
7. **Log.** The agent appends one line to `log.md` only when the schema layout changed (init, first overlay, uninstall).

```text
python3 <atlas-skill>/scripts/atlas.py init --root <root>
python3 <atlas-skill>/scripts/atlas.py schema new <kebab-id> --root <root> [--claim <folder>]
python3 <atlas-skill>/scripts/atlas.py schema install <source> --root <root> [--force]
python3 <atlas-skill>/scripts/atlas.py schema uninstall <id> --root <root>
python3 <atlas-skill>/scripts/atlas.py compile --root <root>
```

You author an overlay outside the store, then install it. Here is the shape, for a `protostar` page type that the companion skill `discuss` contributes:

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

The *memory rung* sets how strictly `compile` reports memory-layer findings.
It is opt-in. If it is absent, it means `info`, and existing stores are not affected.
`schema memory-rung` is its only writer. It does not retype any page.

```text
python3 <atlas-skill>/scripts/atlas.py schema memory-rung --set warn --root <root>
```

## How to ask for it

Ask the agent to install a skill's schema overlay, to add a custom page type, or to remove an overlay.
"Schema overlay" and "schema install" are trigger phrases for Atlas.
The agent mounts the store first, then emits the `schema` card.
To learn about the module without running it, ask "explain schema" or "Atlas help schema".

## Activation card

The agent renders the card as a fenced `text` block after `mount` has set `root`:

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

The card and the loaded module are both required. Without them, Enter is incomplete.

When it finishes, the agent emits an exit receipt with `verb` and the `compile` exit code.
The receipt is incomplete if the contract was edited manually, the CLI was missing, or compile stayed red.

## Boundaries

:::danger
The CLI is the only writer of the contract file (`SCHEMA.json` or `CONTRACT.json`) and `schema.d/`.
Never edit them manually. If the CLI is missing, the agent stops.
:::

- `init` writes core only. It adds no skill namespaces.
- Overlays add types. They must not set `atlas_id`, `compile`, `structure` or `schema_version`. They must not redeclare core types such as `work`, `document` or `experience`.
- Extra root keys are allowed only if the core contract and other overlays do not already use them.
- Never edit `schema.d/<id>.json` in place.
- Knowledge folders stay free layout. Do not claim a folder just because pages live there.
- On a host store, only claimed folders and `schema.d/` receive files. Skill folders do not go at the host root.
- Never skip compile after a write.
- Path [`memory-migrate`](/atlas/modules/memory-migrate/) must not change the memory rung unless the operator explicitly asks.
- Non-goals: sandbox overlays that skip compile, a separate catalog skill for schema, migrating live in-place keys, and changing OKF reserved names or closing the type list.

## Related CLI commands

- [`init`](/atlas/reference/cli/init/)
- [`schema`](/atlas/reference/cli/schema/)
- [`schema new`](/atlas/reference/cli/schema-new/)
- [`schema install`](/atlas/reference/cli/schema-install/)
- [`schema uninstall`](/atlas/reference/cli/schema-uninstall/)
- [`schema upgrade`](/atlas/reference/cli/schema-upgrade/)
- [`schema memory-rung`](/atlas/reference/cli/schema-memory-rung/)
- [`compile`](/atlas/reference/cli/compile/)

## Related modules

- [`mount`](/atlas/modules/mount/) resolves `root` before `schema` runs.
- [`configure`](/atlas/modules/configure/) follows a SCHEMA 2.0 upgrade.
- [`remember`](/atlas/modules/remember/) and [`work`](/atlas/modules/work/) write knowledge pages.
- [`memory-migrate`](/atlas/modules/memory-migrate/) must not set the memory rung on its own.
- [`help`](/atlas/modules/help/) explains `schema` without running it.
