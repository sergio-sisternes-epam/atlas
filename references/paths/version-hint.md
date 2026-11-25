---
name: atlas/paths/version-hint
description: Add one living-page relates_to.ref hint. Do not copy the old body onto tip. Grain stays deferred.
path_id: version-hint
---

# Path: version-hint

## When

A living tip page should point at a prior git version of itself or a closely related path. The tip body stays the current claim. Old wording stays in git.

Not path **history** (read only). Not path **prune** (failed frame leaves tip). Not an ordinary **remember** edge: absent `ref` is tip.

Provenance: atlas-atlas `decision-claim-a-living-version-hints.md` and `decision-relates-to-ref-time-travel.md`.

## Enter

Mount first when this turn has not already set `root`. Then:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: version-hint
path_module: references/paths/version-hint.md
intent: <one line>
root: <atlas store root>
page: <living tip page>
prior: <historical path>
rev: <git rev>
kind: <caller-supplied kind>
```

Read this file before writing the edge. Missing `page`, `prior`, `rev`, or `kind` means incomplete Enter. Ask for the missing field and stop. Do not invent `kind`. Do not copy mount `ref` into `rev`.

One supplied `kind` on this edge does not lock Claim A grain. These stay deferred:

1. Same-path only, or also cross-path.
2. Which kind for future hints.
3. Cadence: every meaningful edit, on request, or on KVA change.
4. How many prior refs: one, a short list, or unbounded.

If the user asks to close any of those, stop. Do not decide them here.

## Procedure

1. **Root** is the mounted store. No git repository: stop.
2. **Current body only.** Edit `page` so the body is the current claim. Do not paste the prior body onto tip.
3. **One hint edge.** Add a `relates_to` item with `path: <prior>`, the caller `kind`, and `ref: <rev>`. Relation `ref` is not mount `ref`. Cross-path is allowed by the shared schema; that is not a decision that same-path-only is closed.
4. **Compile** must succeed before claiming the hint is stored:

   ```text
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```

   A missing HEAD path is allowed only on an item that has `ref`. A tip edge without `ref` still fails if its path is gone.
5. **Recall** of the old wording is path **history**, not a second copy on tip.

## Exit

- Living page has the hint edge and compile exit 0.
- Incomplete if `kind` was invented, the prior body was copied onto tip, or compile is red.

## Non-goals

- Closing the four grain opens.
- `atlas ref prune`.
- Commit, unless the user asked to persist this edit.
