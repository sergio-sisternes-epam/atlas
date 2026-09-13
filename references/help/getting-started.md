---
name: atlas/help/getting-started
description: Bundled first-use baseline. No Atlas mount required.
package_version: 0.11.2
---

# Getting started with Atlas

Atlas is a durable **OKF v0.2** knowledge substrate. Agents use it to query
and remember process memory, decisions, work hubs, and project knowledge
without treating the skill package itself as a store.

This article is the packaged baseline for module **getting-started**. It is
enough for first use. Do not mount, init, remember, query, commit, or push
in order to read it.

## Purpose

- Keep claim-bearing knowledge in an OKF store (`SCHEMA.json` at the store
  root).
- Select one **module** per intent (`help`, `query`, `remember`, …) and
  follow that module; do not improvise from the router alone.
- Run the deterministic CLI from the installed skill directory when a module
  calls for it.

Format rules stay in companion skill **`okf`**. Atlas does not re-implement
them.

## Prerequisites

- APM CLI 0.30.0 or newer.
- Python 3.10 or newer.
- Python dependencies from `<atlas-skill>/scripts/requirements.txt`.
- A git repository in the session before **init**, **mount**, or **remember**.
  Help and this article do not need a store.

Public GitHub consumers do not need a personal access token to install Atlas
or the separate `okf` dependency.

## Install

Consumer install is marketplace-only:

```bash
apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas
apm install atlas@atlas
```

Then install CLI dependencies in the environment that will run Atlas:

```text
python3 -m pip install -r <atlas-skill>/scripts/requirements.txt
```

## Shortest useful first journey

1. Install Atlas as above.
2. Ask **getting-started** (this article) for purpose, storage choices, and
   this journey. Ask **help** with no target to list every installed module.
3. If you already have a store checkout, ask **help mount** or **help query**
   before doing anything. Explanation is not permission to run those modules.
4. If you need a **new** store in the active git repo, ask **help init**, then
   run **init** only when you intend to create one.
5. After a store root exists, use **query** to find knowledge and **remember**
   to write it. Writes end on `atlas compile --root <root>` exit 0.

Do not start by creating a GitHub repository. Do not run mount/init/query
because you asked for help.

## Storage choices (equals)

Both of these are first-class. Neither is a default you must pick to “do it
right”, and **neither includes creating a new host repository**.

| Choice | What it is | When it fits |
|--------|------------|----------------|
| **Existing-repo branch (shared)** | Knowledge lives on isolated branch `atlas` of the consumer repository and mounts as a same-repo submodule at `.atlas/<id>/`. | You want knowledge next to the project that already has a git remote. |
| **Dedicated existing repo** | Knowledge lives in a **separate repository that already exists**. Mesh `strategy` is `dedicated`. | You already have a store remote, or you created that repository yourself outside Atlas. |

- Shared: `atlas store init --strategy shared` (default when strategy is
  omitted on **init**). `remote` is the consumer origin if omitted.
- Dedicated: `atlas store init --strategy dedicated --remote <existing-url>`.
  If `remote` is missing, **ask and stop**. Never `gh repo create`.
- If a dedicated remote does not exist, the human creates it, then retry.
  Atlas never creates the host.
- Move history later with module **migrate** (`migrate_mode: strategy`) /
  `atlas store rehost`. CLI `atlas migrate` still copies into `staging/` only.

Recursive clone of a shared submodule fetches the git object store twice;
that is accepted.

## Next: module help

- No target — “Atlas help” or “what can Atlas do?” lists every installed
  module with a one-line purpose.
- Named — “explain mount”, “what does query need?” loads **only** that
  module’s packaged source.
- Unknown names are rejected with the valid list. Do not invent flags.

CLI option lists come from installed non-mutating `--help` on the matching
verb, not from this article.
