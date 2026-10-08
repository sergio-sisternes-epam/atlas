---
title: migrate
description: Relocate a skill-package store onto a mounted store, or move store history between the shared and dedicated strategies.
sidebar:
  order: 3
source:
  - references/paths/migrate.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/migrate.md: c5e76a514b11bc44069d6d6f48a396910bbead4c
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `migrate` module moves an existing Atlas store.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
`migrate` is generic and has two modes.
It needs Atlas 0.11.0 or later.
Each run handles one own store.

## When

Use `migrate` in one of two cases:

- **`relocate`**: a skill still keeps its store inside the skill package at `references/atlas`. You want to move it to a normal mount at `.atlas/<atlas_id>/`.
- **`strategy`**: you want to move store history to the other storage strategy, from *shared* to *dedicated* or back. A shared store lives on an `atlas` branch of your project repository. A dedicated store has its own repository.

Leave other skills' `references/atlas/` folders alone. Each skill runs `relocate` for itself.

:::note
The CLI has a `migrate` command, but it does something else.
It copies a source into `staging/`, the store's short-lived holding area.
Strategy moves do not use it. They use the `store rehost` command.
:::

## What it does

### Mode `relocate`

1. The agent loads [`mount`](/atlas/modules/mount/) with the same `atlas_id` and `ref`.
   Queries and writes use the root that the `resolve` command prints.
   With no git repository, the agent refuses to persist.
2. The agent moves the gitlink from `references/atlas` to `.atlas/<atlas_id>/`.
   It uses the same path in `atlas-mesh.json`.
   It deletes a `.atlas/` line from `.gitignore` if one is present.
3. The agent replaces every mount command that used `--target references/atlas`.
   It also replaces every `--root` that pointed into the skill tree.
   This covers the SKILL file, the README, path modules, workflow checklists, run receipts and smoke tests that assert the gitlink path.
4. The agent removes the skill-package store at `references/atlas`. That includes the submodule and its empty `.gitmodules` row.
5. Writes go out as two pull requests: first the store repository, then the parent gitlink bump.

The agent does not add a `references/atlas.md` pointer to the skill.
If you need a new Atlas later, use [`init`](/atlas/modules/init/) with an existing remote only.

### Mode `strategy`

1. The agent reads the mesh `strategy` field. A missing field means *dedicated*.
   When the field is present, the agent does not infer the strategy from the id and ref.
2. A dedicated destination needs an **existing** git remote. Atlas never creates a host repository.

   ```text
   python3 <atlas-skill>/scripts/atlas.py store rehost --destination-strategy <shared|dedicated> [--remote <url>] --json
   ```

3. Atlas pushes the history, fast-forward only.
   - Unrelated history at the destination fails closed.
   - Atlas does not rewrite or import pages.
   - There is no dual write. Atlas removes the old mount only after the new gitlink exists.
4. The mesh `id`, `ref` and `strategy` now match the destination.
   For a shared destination, `ref` is `atlas`. Atlas then applies the GitHub driver, a ruleset that blocks direct pushes. On the reverse move, it does not strip rulesets.
5. The `compile` command must pass on the new root. *Compile* checks the contract shape, required frontmatter and required links. The agent does not write to the old root.

## How to ask for it

Ask the agent to migrate a store, and say which mode you want.
For example: "relocate this skill's references/atlas store" or "move this Atlas from shared to dedicated".
For a dedicated destination, give the existing store URL.
To learn about the module without running it, ask `/atlas help migrate` or "explain migrate".

## Activation card

The agent renders the card as a fenced `text` block. The `migrate` card has these fields:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: <skill>
path: migrate
path_module: references/paths/migrate.md
intent: <one line>
migrate_mode: relocate | strategy
atlas_id: <host/org/repo>
ref: main
destination_strategy: shared | dedicated
remote: <existing dedicated URL when destination is dedicated>
```

- `migrate_mode` is always required. Without it, the card is incomplete.
- For `relocate`, `atlas_id` is required. It comes from the skill's `.gitmodules` URL, in the form `host/org/repo`.
- For `strategy`, `destination_strategy` is required. If it equals the current strategy, Atlas fails closed.
- `remote` is needed when the destination is dedicated.

## Boundaries

- Do not copy the `migrate`, `mount` or `init` module files into a skill.
- One own store per run.
- `migrate` never creates a host repository.
- Strategy moves do not use the CLI `migrate` command.
- Strategy moves are fast-forward only. They do not rewrite pages and do not dual-write.

## Related CLI commands

- [`store rehost`](/atlas/reference/cli/store-rehost/)
- [`mount`](/atlas/reference/cli/mount/)
- [`resolve`](/atlas/reference/cli/resolve/)
- [`compile`](/atlas/reference/cli/compile/)
- [`migrate`](/atlas/reference/cli/migrate/) (copies into staging; not used for strategy moves)

## Related modules

- [`mount`](/atlas/modules/mount/) mounts the store during `relocate`.
- [`init`](/atlas/modules/init/) creates a new Atlas on an existing remote.
