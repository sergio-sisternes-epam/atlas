---
name: atlas/paths/atlas-dream
description: Use this path only when the operator explicitly asks for a dream or consolidation report on an Atlas target. It lists duplicate pages and claims, contradiction candidates, and superseded pages that are not marked, each with verbatim path:line quotes and a suggested supersede link. Read-only. Trigger on atlas-dream, dream pass, consolidation report, find contradictions, find duplicates, superseded but not marked. Not on install. Not on compile. Not a separate package. It never rewrites memory.
path_id: atlas-dream
---

# Path: atlas-dream

Not a separate package. Not a memory layer.

Dream is the report half of offline consolidation. It reads a target and lists
candidates; a reviewer decides. Remember stays the only writer of claims, and
forget stays the only way to drop one. This path never rewrites memory, so it is
not sleep.

## When

The operator explicitly chooses dream and names a target: one folder, or the
store root. Good moments are idle windows, a schedule, or before a release.
Never select this path from install, compile, init, or memory-migrate.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: atlas-dream
path_module: references/paths/atlas-dream.md
intent: <one line>
root: <atlas store root>
target: <folder inside root> | .
out_dir: <folder outside the store>
```

Then read this file.

## Procedure

1. Stop unless this path was explicitly chosen. Not on install. Not on compile.
2. Run the helper with `--out-dir` outside the store:
   `python3 <atlas-skill>/scripts/atlas_dream.py report --root <root> --target <folder|.> --out-dir <dir>`.
   It writes `dream.json` and `dream.md` there and nothing in the store. It
   refuses an out-dir inside the store and a scope above `--cost-ceiling`
   (default 400 pages). Exit 0 no findings, 1 findings listed, 2 refused.
3. Read every finding against its quotes. Each kind is a candidate, not a verdict:
   - `supersede-unmarked`: a live page is the target of a `supersedes` edge.
     If the newer page supersedes only part of it, annotate that part instead
     of marking the whole page superseded.
   - `conflict-candidate`: two similar claims differ in polarity (never, not,
     cannot) or, across two pages, in a quantity. Issue refs, dates, times,
     versions, hashes and tally lines are ignored as numbers. Expect many to be
     different scopes or dated snapshots, not conflicts.
   - `same-title`: two live pages share a title and no `supersedes` edge.
   - `duplicate-page` and `duplicate-claim`: near-identical bodies or lines.
4. For each finding the reviewer keeps, pick one action and record why:
   amend the stale claim through path remember; link the newer page with
   `relates_to` kind `supersedes` and mark the older one superseded (or path
   atlas-forget); merge duplicates into one canonical page; or note the two
   scopes. Do not delete a page to resolve a finding.
5. Run `atlas compile --root <root>` after any edit the reviewer makes.

## Rules

- Quote, do not paraphrase. A finding without both quotes is not a finding.
- Newer is not automatically right. Authority and scope decide which claim
  wins; record that rule next to the fix.
- Keep history: supersede and annotate instead of deleting.
- Thresholds (`--page-similarity`, `--claim-similarity`, `--min-claim-chars`)
  trade recall for noise. Tune them per store; do not treat a clean report as
  proof that no contradiction exists.

## Non-goals

- Applying any fix, writing in the store, or pushing.
- Running inside install or compile.
- Semantic judgement: the helper matches text, a reviewer decides meaning.
- Sleep: automatic rewriting or merging of memory.
