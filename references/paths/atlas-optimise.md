---
name: atlas/paths/atlas-optimise
description: Use this path only when the operator explicitly asks to consolidate Atlas folder structure, like a dream phase. Trigger on atlas-optimise, consolidate folders, dream phase. Not on install. Not on compile. Expensive and scales with the chosen store scope. Not a separate package.
path_id: atlas-optimise
---

# Path: atlas-optimise

Not a separate package. Not a memory layer.

## When

The operator explicitly chooses consolidation of folder structure. Never select this path from install, compile, init, or memory-migrate.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: atlas-optimise
path_module: references/paths/atlas-optimise.md
intent: <one line>
root: <atlas store root>
```

Then read this file.

## Procedure

1. Stop unless this path was explicitly chosen. Not on install. Not on compile.
2. The operator names the scope: one folder, or the store root. Cost scales with that scope, including the whole store when the root is named.
3. Consolidation is folder structure only. Do not invent gist text. A gist description must remain an exact substring of the derived memory body or description.
4. If a move would leave a gist with no schema, a schema missing from index.md, or a stale upper page, stop and load references/paths/remember.md. Do not weaken compile.
5. hub.md is not a memory level. One gist still forces one schema. A second schema stays legal. Suffixes stay search handles. index.md stays a cue list, not a content layer.

## Non-goals

- Running inside install or compile.
- memory-migrate.
- Inventing a new memory layer.
