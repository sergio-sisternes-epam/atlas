---
title: atlas-memorise
description: Choose the right memory layer before a write, then follow the remember module.
sidebar:
  order: 7
source:
  - references/paths/atlas-memorise.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/atlas-memorise.md: eaff0f21d11ce7595c22dbd4c766e192b414e1fe
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `atlas-memorise` module is a short check before the agent writes memory.
It helps the agent choose the layer for a new claim.
Then it passes the write to the [`remember`](/atlas/modules/remember/) module.
It is not a separate package and it is not a memory layer.

Atlas uses four optional layers:

- The *index* (`index.md`) is a cue list. It points at schemas. It is not a content layer.
- A *schema* is a folder-level page that lists the gists in that folder.
- A *gist* is a short summary page derived from one or more memory pages.
- A *memory* is the page that holds the full claim.

## When

Use `atlas-memorise` when the agent is about to write claim-bearing knowledge.
The agent must choose the layer first.

## What it does

1. The module writes nothing. It does not run compile.
2. The agent checks the layer model:
   - The four layers are optional progressive disclosure.
   - A page can be in the index without a schema.
   - A page may skip the gist.
   - When a gist exists, that gist needs one schema. A second schema is legal.
   - The suffixes `.schema.md`, `.gist.md` and `.memory.md` are search handles.
   - `index.md` is a cue list, not a content layer.
   - `hub.md` is not a memory level.
   - Non-memory types are not forced through a typed middle layer.
3. The agent loads the [`remember`](/atlas/modules/remember/) module and follows it for the write.
   It does not rewrite sibling schemas in this module.

## How to ask for it

Ask with words such as "memorise", "atlas-memorise", "which layer should I write" or "schema versus gist versus memory".
To learn about the module without running it, ask `/atlas help atlas-memorise`.

## Activation card

The agent renders the card as a fenced `text` block. The `atlas-memorise` card has these fields:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: atlas-memorise
path_module: references/paths/atlas-memorise.md
intent: <one line>
root: <atlas store root>
```

`root` is the store root that [`mount`](/atlas/modules/mount/) resolved.
After the card, the agent reads the module file.

## Boundaries

- The module does not restate the `remember` procedure.
- It does not recall, forget, optimise, install or compile.
- It does not answer questions or drop memory.

## Related CLI commands

None directly.
The [`remember`](/atlas/modules/remember/) module does the write and runs the [`compile`](/atlas/reference/cli/compile/) command.

## Related modules

- [`remember`](/atlas/modules/remember/) does the write.
- [`atlas-recall`](/atlas/modules/atlas-recall/) is the matching read-side module.
- [`atlas-forget`](/atlas/modules/atlas-forget/) drops memory.
- [`atlas-optimise`](/atlas/modules/atlas-optimise/) fills and tidies layers on request.
- [`mount`](/atlas/modules/mount/) sets `root` first.
