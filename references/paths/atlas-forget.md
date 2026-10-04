---
name: atlas/paths/atlas-forget
description: Use this path when an agent should drop Atlas memory with a keep, vary, or abandon choice. Trigger on atlas-forget, forget this page, drop this memory, abandon a gist. Not a separate package. Do not use it to invent traffic values or to delete files.
path_id: atlas-forget
---

# Path: atlas-forget

Not a separate package. Not a memory layer.

The atlas repo does not define keep / vary / abandon. For this path only, KVA means three actions: keep leaves the page; vary changes it through path remember so the owning gist and schema cascade; abandon marks it out of default recall with the existing traffic value `kva: terminated`. This is not a new theory and not a new field value.

## When

An operator is dropping memory.

## Enter

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

Then read this file.

## Procedure

1. Not on install. Not on compile. The operator names the pages.
2. For each page choose one of keep, vary, or abandon.
3. keep: write nothing.
4. vary: load references/paths/remember.md and follow it. Do not rewrite sibling schemas.
5. abandon: load catalog skill discuss and path references/paths/terminate.md so the page gets `kva: terminated`. Do not delete the file. Do not add keep, vary, or abandon as `kva` values.
6. hub.md is not a memory level.

## Non-goals

- A second KVA theory.
- File deletion.
- Optimise, install, or compile.
