---
name: atlas/paths/atlas-memorise
description: Use this path before writing Atlas memory so the agent follows the four-layer discipline. Trigger on memorise, atlas-memorise, which layer to write, schema versus gist versus memory. Not a separate package. Hand off to path remember. Do not use it to answer questions or to drop memory.
path_id: atlas-memorise
---

# Path: atlas-memorise

Not a separate package. Not a memory layer.

## When

An agent is about to write claim-bearing knowledge and must choose the layer first.

## Enter

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

Then read this file.

## Procedure

1. This path writes nothing and does not compile.
2. Apply the locked model only as a check: one gist forces one schema; a second schema is legal; suffixes are search handles; index.md is a cue list, not a content layer. hub.md is not a memory level.
3. Load references/paths/remember.md and follow that path for the write. Do not rewrite sibling schemas here.

## Non-goals

- Restating path remember.
- Recall, forget, optimise, install, or compile.
