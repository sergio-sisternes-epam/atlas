---
title: mount
description: Mount an Atlas store into your git repository if it is missing, then resolve its root.
sidebar:
  order: 1
source:
  - references/paths/mount.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/mount.md: 22afa4b8ecfec5df53f0b721ae7d07cf86106ec3
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `mount` module makes an Atlas store available in your project.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
`mount` is generic: the store comes from the activation card.
The module file itself is not a store.

## When

Use `mount` before any formal query or any change to a store.
The agent emits `mount` first, then the operational module, such as `recall`, `remember`, `work` or `landscape`.

## What it does

1. If there is no git repository, the agent stops. It does not mount and does not persist anything.
2. The agent mounts the store if it is missing.
   It does not pass `--target`, so the store mounts as a git submodule at `<git-root>/.atlas/<atlas_id>/`.
   Then it resolves the store root:

   ```text
   python3 <atlas-skill>/scripts/atlas.py mount <atlas_id> --ref <ref>
   python3 <atlas-skill>/scripts/atlas.py resolve <atlas_id>
   ```

3. The agent sets the card field `root` to the resolved path.
   It then uses that root (`--root`) for recall, remember, work and landscape.

Some details from the module:

- Generic GitHub token variables apply only to `github.com` and `*.ghe.com`.
  Credentials for GitHub Enterprise Server need an exact `GH_HOST` match.
  For an unmatched host, Atlas uses anonymous HTTPS with credential helpers turned off.
  For private repositories on such a host, use `--ssh` or log in to that host with the GitHub CLI.
- A completely empty remote is a valid mount for a new Atlas.
  Git cannot register a submodule without a commit.
  So Atlas creates a deterministic, local, empty bootstrap commit on `ref` and registers the submodule.
  It does not change the remote.
  Continue with the [`init`](/atlas/modules/init/) module before you commit the consumer repository.
- A non-empty remote that does not have `ref` still fails. Atlas does not create a divergent branch.
- A failed mount rolls back the target, the submodule metadata, the index and the local git configuration.
- On a remount, the mesh `strategy` is kept. A missing `strategy` means *dedicated*.
  Shared mounts track `branch = atlas` in `.gitmodules`. The nested checkout must not stay detached.

## How to ask for it

You do not usually ask for `mount` directly.
When you ask Atlas to query or change a store, for example with `/atlas` in an agent session, the agent emits `mount` first.
To learn about the module without running it, ask `/atlas help mount` or "explain mount".

## Activation card

The agent renders the card as a fenced `text` block. The `mount` card has these fields:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: mount
path_module: references/paths/mount.md
intent: <one line>
atlas_id: <host/org/repo>
ref: <branch>
root: <set after resolve>
```

`atlas_id` and `ref` come from the card. A missing `atlas_id` means the card is incomplete.

## Boundaries

- No git repository means no mount and no persistence.
- The agent never mounts or writes at `<skill>/references/atlas`.
- The agent does not write into the calling skill package.
- `mount` does not create a divergent branch on a non-empty remote.

## Related CLI commands

- [`mount`](/atlas/reference/cli/mount/)
- [`resolve`](/atlas/reference/cli/resolve/)

## Related modules

- [`init`](/atlas/modules/init/) creates a new Atlas.
- [`recall`](/atlas/modules/recall/), [`remember`](/atlas/modules/remember/), [`work`](/atlas/modules/work/) and [`landscape`](/atlas/modules/landscape/) run after `mount` sets `root`.
- [`help`](/atlas/modules/help/) explains modules without mounting.
