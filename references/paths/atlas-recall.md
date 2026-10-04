---
name: atlas/paths/atlas-recall
description: Use this path when an agent needs to navigate the four-layer discipline while reading. Trigger on atlas-recall, navigate layers, where to stop reading. Not a separate package. Load path recall and follow it. Do not use it to write pages.
path_id: atlas-recall
---

# Path: atlas-recall

Not a separate package. Not a memory layer.

## When

An agent is reading an Atlas and needs the four-layer navigation discipline.

## Enter

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

Then read this file.

## Procedure

1. Load references/paths/recall.md and follow that path.
2. Do not restate that procedure in this file.
3. This path is not a memory layer. hub.md is not a memory level.

## Non-goals

- A second read procedure.
- Writing, compile, install, forget, or optimise.
