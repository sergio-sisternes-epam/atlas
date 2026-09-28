---
name: atlas/paths/history
description: Read one store path at a git rev. A relates_to.ref edge is not a tip hop.
path_id: history
---

# Path: history

## When

The ask is historical, a `relates_to` item has `ref`, or the user wants a page as it was at a rev. This path only reads. Writing a living hint is path **version-hint**. Dropping a failed frame from tip is path **prune**.

## Enter

Mount first when this turn has not already set `root`. Then:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: history
path_module: references/paths/history.md
intent: <one line>
root: <atlas store root>
page: <store-relative path>
rev: <git rev>
```

Read this file before `atlas ref show`. Missing card, unloaded module, missing `page`, or missing `rev` means incomplete Enter. Do not guess the rev. Do not copy mount `ref` (the branch a store tracks) into `rev`.

## Procedure

1. **Root** is the mounted store. No git repository: stop. Do not read HEAD as a substitute.
2. **Do not hop.** If the edge has `ref`, that path on HEAD is not the historical page. Do not open it to answer the historical ask.
3. **Show.** Print the blob. Do not write it back onto tip.

   ```text
   python3 <atlas-skill>/scripts/atlas.py ref show <page> --ref <rev> --root <root>
   ```

4. **Refuse is final.** Path escape, an Atlas-managed root (`staging`, `templates`, `mesh`, `schema.d`, `.atlas-index`), a rev that does not resolve in that repo, a missing blob, or a historical entry that is not a regular file (including a symlink blob) is a stop. Staging never answers, including through git history. Do not search the worktree for a lookalike.

## Exit

- Historical bytes shown, or an explicit refusal.
- Tip tree unchanged. No compile. No commit.

## Non-goals

- Search mode for history. Default search stays on the tip.
- Compiling `ref` edges.
- Choosing Claim A grain (same-path, kind, cadence, count).
- Prune or supersede.
