---
title: Choose storage
description: Compare shared storage on the consumer branch atlas with a dedicated, existing store repository.
source:
  - references/help/getting-started.md
  - references/paths/init.md
  - scripts/atlas_cli/commands/storecmd.py
source_sha:
  references/help/getting-started.md: b1c704e59354a1bacd0e4b98c53dbde67b3e3d0c
  references/paths/init.md: 0b59b309470641cc80d67c91707874f2248f2ff6
  scripts/atlas_cli/commands/storecmd.py: 5e60d3a0cdcbec2504347762c9b48076ec55cb18
source_tag: v0.13.0-beta.13
---

An Atlas *store* holds your knowledge pages.
You choose where the store lives. There are two equal choices.
Neither choice is the “right” one.

:::note
Atlas never creates a host repository.
Neither choice includes creating a new repository on a git host.
:::

## The two choices

| Choice | What it is | When it fits |
| --- | --- | --- |
| **Shared** (existing-repo branch) | Knowledge lives on the isolated branch `atlas` of your project repository. It mounts as a same-repo submodule at `.atlas/<id>/`. | You want knowledge next to a project that already has a git remote. |
| **Dedicated** (existing repo) | Knowledge lives in a separate repository that already exists. The mesh `strategy` is `dedicated`. | You already have a store remote, or you created that repository yourself outside Atlas. |

The *mesh* is the list of stores that your project mounts.
Each mesh entry records its `strategy`.
An entry without a `strategy` counts as dedicated.

## Shared storage

Shared is the default when you do not name a strategy.
The remote is your project’s `origin` if you do not pass `--remote`.

```text
python3 <atlas-skill>/scripts/atlas.py store init --strategy shared
```

- Atlas creates or reuses the branch `atlas` in your project repository.
- If the branch is missing, Atlas starts it as an empty orphan tree and adds the SCHEMA files.
  It does not copy your default branch.
- If the branch `atlas` exists but has no contract file (`SCHEMA.json` or `CONTRACT.json`), Atlas fails closed.
- `.gitmodules` records `branch = atlas`.
- On GitHub, Atlas then adds a ruleset that blocks direct pushes to `atlas`.
  It pushes the empty `atlas` branch first, so the ruleset does not block that push.
  On a self-hosted host, Atlas prints a warning and continues.
- A recursive clone fetches the git objects of a same-repo submodule twice. That cost is accepted.

## Dedicated storage

Dedicated storage needs an existing store repository:

```text
python3 <atlas-skill>/scripts/atlas.py store init --strategy dedicated --remote <existing-url>
```

- If you do not give `--remote`, the agent asks for it and stops.
  The CLI also fails: dedicated init requires `--remote`.
- If the remote does not exist, create the repository yourself, then retry.
  Atlas never creates it for you.

## Change your mind later

You can move store history between shared and dedicated later.
Use the [`migrate`](/atlas/modules/migrate/) module with `migrate_mode: strategy`.
It uses the [`store rehost`](/atlas/reference/cli/store-rehost/) command:

```text
python3 <atlas-skill>/scripts/atlas.py store rehost --destination-strategy shared|dedicated [--remote <url>] [--id <atlas_id>]
```

The [`migrate`](/atlas/reference/cli/migrate/) command is different.
It only copies content into `staging/`, the short-lived area for content that is not yet compiled.

## Next steps

- Read the [`init`](/atlas/modules/init/) module before you create a store.
- See the [`store init`](/atlas/reference/cli/store-init/) reference.
