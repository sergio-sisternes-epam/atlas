---
title: atlas-recall
description: Navigate the four memory layers while reading by loading the recall module.
sidebar:
  order: 8
source:
  - references/paths/atlas-recall.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/atlas-recall.md: 5f806decdea29071efb9f3fbe82a04bd0f3eafa9
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `atlas-recall` module points the agent to the read procedure.
It loads the [`recall`](/atlas/modules/recall/) module and follows it.
It does not restate the walk.
It is not a separate package and it is not a memory layer.

Atlas stores knowledge in four optional layers.
Recall cues schemas from the `index.md` cue list.
Then it walks from *schema* (folder summary) to *gist* (short summary) to *memory* (full claim).
It stops when the current layer answers the question.

## When

Use `atlas-recall` when the agent reads an Atlas and needs the four-layer navigation discipline.
For example, the agent needs to know where to stop reading.

## What it does

1. The agent loads the [`recall`](/atlas/modules/recall/) module and follows it.
2. The module does not restate that procedure.
3. The module is not a memory layer. `hub.md` is not a memory level.

## How to ask for it

Ask with words such as "atlas-recall", "navigate layers" or "where to stop reading".
To learn about the module without running it, ask `/atlas help atlas-recall`.

## Activation card

The agent renders the card as a fenced `text` block. The `atlas-recall` card has these fields:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: atlas-recall
path_module: references/paths/atlas-recall.md
intent: <one line>
root: <atlas store root>
```

`root` is the store root that [`mount`](/atlas/modules/mount/) resolved.
After the card, the agent reads the module file.

## Boundaries

- The module is not a second read procedure.
- It does not write pages.
- It does not compile, install, forget or optimise.

## Related CLI commands

None directly.
The [`recall`](/atlas/modules/recall/) module runs the [`recall run`](/atlas/reference/cli/recall-run/) command.

## Related modules

- [`recall`](/atlas/modules/recall/) holds the read procedure.
- [`atlas-memorise`](/atlas/modules/atlas-memorise/) is the matching write-side check.
- [`atlas-forget`](/atlas/modules/atlas-forget/) drops memory.
- [`atlas-optimise`](/atlas/modules/atlas-optimise/) fills and tidies layers on request.
- [`mount`](/atlas/modules/mount/) sets `root` first.
