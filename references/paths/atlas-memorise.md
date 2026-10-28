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
2. Apply the locked model only as a check: default write is memory + gist + schema. Skip only as a recorded one-line exception (a single short fact, or an index-first-class non-memory type such as work hub, decision, lesson, recipe). Compile still does not require a schema for index membership and does not hard-fail a missing gist; when a gist exists, that gist forces one schema; a second schema is legal. Suffixes are search handles. index.md is a cue list, not a content layer. hub.md is not a memory level. Non-memory types are not forced through a typed middle extension.
3. Multi-item check: if the source holds several distinct items, do not file them as bullets on one page. Follow **Split a multi-item source** in remember.md (one memory and one gist each; one schema per folder; source page links out).
4. Load references/paths/remember.md and follow that path for the write. Do not rewrite sibling schemas here.

## Non-goals

- Restating path remember.
- Recall, forget, optimise, install, or compile.
