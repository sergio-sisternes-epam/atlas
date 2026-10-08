---
title: atlas-forget
description: Drop Atlas memory by choosing keep, vary or abandon for each page the operator names.
sidebar:
  order: 9
source:
  - references/paths/atlas-forget.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/atlas-forget.md: beab6652f5edf5700e2e166f4d6c6e5c684fe38a
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `atlas-forget` module drops memory from an Atlas store.
For each page, the agent makes one of three choices: keep, vary or abandon.
It does not add a new traffic value and it does not delete files.
It is not a separate package and it is not a memory layer.

Atlas itself does not define keep, vary and abandon.
In this module only, they mean three actions:

- **keep** leaves the page as it is.
- **vary** changes the page through the [`remember`](/atlas/modules/remember/) module, so the owning gist and schema update in turn.
- **abandon** takes the page out of default recall.
  It uses the existing traffic value `kva: terminated`.

This is not a new theory and not a new field value.

## When

Use `atlas-forget` when an operator drops memory.

## What it does

1. The module never runs on install or on compile. The operator names the pages.
2. For each page, the agent chooses keep, vary or abandon.
3. **keep:** the agent writes nothing.
4. **vary:** the agent loads the [`remember`](/atlas/modules/remember/) module and follows it.
   It does not rewrite sibling schemas.
5. **abandon:** the agent loads the companion skill `discuss` and its `terminate` path.
   The page gets `kva: terminated`.
   The agent does not delete the file.
   It does not add keep, vary or abandon as `kva` values.
6. `hub.md` is not a memory level.

## How to ask for it

Ask with words such as "atlas-forget", "forget this page", "drop this memory" or "abandon a gist".
Name the pages you want to drop.
To learn about the module without running it, ask `/atlas help atlas-forget`.

## Activation card

The agent renders the card as a fenced `text` block. The `atlas-forget` card has these fields:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: atlas-forget
path_module: references/paths/atlas-forget.md
intent: <one line>
root: <atlas store root>
```

`root` is the store root that [`mount`](/atlas/modules/mount/) resolved.
After the card, the agent reads the module file.

## Boundaries

- The module is not a second keep, vary and abandon theory.
- It does not delete files.
- It does not invent traffic values.
- It does not optimise, install or compile.

:::note
Abandon needs the companion skill `discuss`.
If `discuss` is not available, the agent stops and tells you.
It does not guess the terminate procedure.
:::

## Related CLI commands

None directly.
The [`remember`](/atlas/modules/remember/) module handles a vary and runs the [`compile`](/atlas/reference/cli/compile/) command.

## Related modules

- [`remember`](/atlas/modules/remember/) handles a vary.
- [`atlas-memorise`](/atlas/modules/atlas-memorise/) checks the layer before a write.
- [`atlas-recall`](/atlas/modules/atlas-recall/) navigates the layers while reading.
- [`atlas-optimise`](/atlas/modules/atlas-optimise/) fills and tidies layers on request.
- [`mount`](/atlas/modules/mount/) sets `root` first.
