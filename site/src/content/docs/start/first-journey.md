---
title: First journey
description: The shortest useful path from install to your first green compile.
source:
  - references/help/getting-started.md
  - README.md
source_sha:
  references/help/getting-started.md: b1c704e59354a1bacd0e4b98c53dbde67b3e3d0c
  README.md: 504c2d65ab2b42dabe8a456d0ce08d9ca85f3de7
source_tag: v0.13.0-beta.13
---

This page shows the shortest useful first journey with Atlas.
You talk to Atlas in an agent session with `/atlas`.
Starting is asking Atlas how to do it:

```text
/atlas How can I get started?
```

## Steps

1. [Install Atlas](/atlas/start/install/).
2. Ask the [`getting-started`](/atlas/modules/getting-started/) module for the purpose, the storage choices and this journey.
   Ask the [`help`](/atlas/modules/help/) module with no target to list every installed module.
3. If you already have a store checkout, ask **help mount** or **help recall** first.
   An explanation is not permission to run those modules.
4. If you need a **new** store in the active git repository, ask **help init**.
   Run [`init`](/atlas/modules/init/) only when you intend to create a store.
5. When a store root exists, use [`recall`](/atlas/modules/recall/) to find knowledge.
   Use [`remember`](/atlas/modules/remember/) to write it.
   A write ends when `compile` exits with code 0:

   ```text
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```

`<root>` is the root directory of your store.
Exit code 0 is a *green* compile.
See the [`compile`](/atlas/reference/cli/compile/) reference.

:::note
Do not start by creating a GitHub repository.
Do not run mount, init or recall just because you asked for help.
:::

## Ask for help

- With no target, “Atlas help” or “what can Atlas do?” lists every installed module with a one-line purpose.
- With a name, for example “explain mount” or “what does recall need?”, the agent loads only that module’s packaged source.
- The agent rejects an unknown name and shows the valid list. It does not invent flags.

Option lists come from the non-mutating `--help` of the installed CLI, not from help articles.

## Next steps

- [Choose where your knowledge lives](/atlas/start/choose-storage/).
- Browse all [modules](/atlas/modules/).
