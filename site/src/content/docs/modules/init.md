---
title: init
description: Scaffold a new Atlas store in the active git repository, with a shared or dedicated storage strategy.
sidebar:
  order: 2
source:
  - references/paths/init.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/init.md: 0b59b309470641cc80d67c91707874f2248f2ff6
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `init` module creates a new Atlas.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
`init` is generic: any skill or session that needs a **new** store can use it.
The module never creates a repository on a git host.

## When

Use `init` when you need a new Atlas and no store exists yet.
The agent emits `init` instead of [`mount`](/atlas/modules/mount/).
To use an existing store, use `mount` instead.

`init` has two *storage strategies*:

- **shared** is the default. Knowledge lives on a branch named `atlas` in your own project repository (the *consumer*).
- **dedicated** uses a separate store repository. That repository must already exist.

An *embedded* store is something else.
It means a store inside a skill package at `references/atlas`.
The [`migrate`](/atlas/modules/migrate/) module moves those.

## What it does

1. If there is no git repository in the session, the agent stops.
2. The agent picks the remote.
   For shared, the remote is the consumer origin if you do not give one.
   For dedicated, the remote must be an **existing** store repository.
   Then the agent bootstraps the store and resolves its root:

   ```text
   python3 <atlas-skill>/scripts/atlas.py store init --strategy <shared|dedicated> [--remote <url>] --json
   python3 <atlas-skill>/scripts/atlas.py resolve <atlas_id>
   ```

   The plain `init` command with `--root` only writes the SCHEMA files.
   The *SCHEMA* is the store's contract file, which defines page types and rules.
   Store bootstrap is the `store init` command.
3. **Shared:** Atlas creates or reuses the `atlas` branch on the consumer.
   - If the branch is missing, Atlas starts an empty orphan tree and adds the SCHEMA. It does not copy the default branch.
   - If an `atlas` branch exists without `SCHEMA.json`, Atlas fails closed.
   - The mesh entry for the store records the consumer as `id`, `atlas` as `ref` and `shared` as `strategy`.
   - `.gitmodules` records `branch = atlas`.
   - On a GitHub host, Atlas then adds a ruleset that blocks direct pushes. It pushes the empty `atlas` branch first, so the ruleset does not block the first push. On a self-hosted git server, Atlas prints a warning and continues.
4. **Dedicated:** Atlas mounts the existing remote. It never creates the host repository.
   The mesh entry records `strategy` as `dedicated`.
   Older mesh files with no `strategy` field also count as dedicated.
5. If the clone or mount fails because the remote does not exist, the agent tells you to create the repository yourself. Then you retry. The agent does not create it.
6. The agent sets the card field `root`. Later queries and writes use that root.

A shared store is a submodule of its own repository.
So a `--recursive` clone fetches the consumer's git objects twice.
Atlas accepts that cost. It does not switch to a git worktree.

## How to ask for it

Ask the agent to create a new Atlas, for example "create a new Atlas for this project".
Say "dedicated" and give the existing store URL if you want a separate repository.
To learn about the module without running it, ask `/atlas help init` or "explain init".

## Activation card

The agent renders the card as a fenced `text` block. The `init` card has these fields:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: init
path_module: references/paths/init.md
intent: <one line>
strategy: shared | dedicated
remote: <consumer origin, or existing dedicated store URL>
atlas_id: <host/org/repo, or set after id>
root: <set after resolve>
```

- `strategy` defaults to `shared` when you omit it. The SKILL.md router card shows `strategy: shared`.
- If `strategy` is `dedicated` and `remote` is missing, the agent asks for an existing store remote and stops. It does not invent one.

## Boundaries

- No git repository means no store.
- `init` never creates a host repository. It does not call any host API to create one.
- The agent does not write the new store into a skill package. It does not use `--target references/atlas`.
- An existing `atlas` branch without `SCHEMA.json` fails closed.

## Related CLI commands

- [`store init`](/atlas/reference/cli/store-init/)
- [`resolve`](/atlas/reference/cli/resolve/)
- [`init`](/atlas/reference/cli/init/) (writes SCHEMA files only)

## Related modules

- [`mount`](/atlas/modules/mount/) uses an existing store instead of creating one.
- [`migrate`](/atlas/modules/migrate/) relocates a skill-package store or moves a store between strategies.
- [`recall`](/atlas/modules/recall/) and [`remember`](/atlas/modules/remember/) run on the new root.
