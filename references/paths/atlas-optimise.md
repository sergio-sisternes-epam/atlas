---
name: atlas/paths/atlas-optimise
description: Use this path only when the operator explicitly asks to optimise an Atlas target (one folder or the store root), like a dream phase. It repairs the four-layer discipline with existing page text and clusters folders by subject naming, with a per-folder migration task list and a dry-run first. Trigger on atlas-optimise, optimise this atlas, consolidate folders, dream phase, finish the layers, fix dead frame cues. Not on install. Not on compile. Expensive and scales with the chosen target. Not a separate package.
path_id: atlas-optimise
---

# Path: atlas-optimise

Not a separate package. Not a memory layer.

## When

The operator explicitly chooses optimise and names a target: one folder, or
the store root. Never select this path from install, compile, init, or
memory-migrate.

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
target: <folder inside root> | .
phase: plan | apply
```

Then read this file. A missing target means Enter is incomplete: ask the
operator for one. Do not assume the store root.

## Locked model this path enforces

Recall walks index, then schema, then gist, then memory. `index.md` is a cue
list, not content. One gist forces one schema. A second schema is legal when
the subject changes. A folder with zero gists needs no schema. `hub.md` is not
a memory layer. Suffixes `.schema.md`, `.gist.md`, `.memory.md` are search
handles; frontmatter `type` is authoritative. Compile fails only on a gist
with no schema, a schema missing from index, or a stale upper page. This path
adds no compile check.

## Helper

```bash
python3 <atlas-skill>/scripts/atlas_optimise.py plan  --root <root> --target <folder|.> --out-dir <dir outside the store> [--subject-folder <folder>:<stem>]...
python3 <atlas-skill>/scripts/atlas_optimise.py apply --root <root> --target <folder|.> --plan <out-dir>/plan.json [--include-opt-in] [--confirm <task-id>]...
```

The helper is standalone. `atlas.py` has no optimise command and nothing in
install, init, compile, or memory-migrate calls it. It never writes
`CONTRACT.json` or `SCHEMA.json`. Exit codes: plan 0 no tasks, 1 tasks listed,
2 refused. apply 0 no residual tasks, 1 residual tasks, 2 refused with nothing
written.

## Procedure

1. Stop unless this path was explicitly chosen. Not on install. Not on compile.
2. Confirm the target. Cost scales with it, including the whole store when the
   root is named.
3. **Plan (dry-run, always first).** Run `plan` with `--out-dir` outside the
   store. It writes nothing in the store and refuses an out-dir inside it. It
   writes `plan.json` and one migration task list per top-level folder
   (`tasks/<folder>.md`, `tasks/root.md` for root files). Show the operator the
   task lists before any apply.
4. **Precondition.** If the plan has a `contract-precondition` task (the store
   still uses `SCHEMA.json`, or has `type: frame` pages), every other task is
   blocked. Do not run memory-migrate from here. The operator may choose path
   memory-migrate `--batch contract-file`; then re-run plan.
5. **Do not stop early.** Pages that already share a parent are not a reason
   to stop. Dead `frame.md` cues and gist descriptions missing from the memory
   above them are the work. Read every folder's list.
6. **Four-layer repair tasks** (each task names its class):
   - `dead-index-cue` (auto): remove an `index.md` list line whose only link
     points at a missing page, such as a deleted `frame.md`.
   - `schema-index-cue` (auto): cue a schema page from its folder `index.md`,
     labelled with the schema's own title.
   - `uncovered-gist`: auto when the folder has exactly one schema (add the
     gist to its `relates_to`); handoff when it has none or several.
   - `dead-schema-member` (auto): drop a schema `relates_to` entry whose gist
     no longer exists.
   - `stale-gist-description`: auto copies the memory page's existing
     `description` verbatim up into the gist. The memory text is never edited.
     If the memory has no plain one-line description, the task is handoff to
     path remember.
   - `layer-skip-cue` (confirm): an `index.md` line that cues a gist or memory
     page directly. Removal changes what the index lists, so only on
     `--confirm`.
   - `layer-suffix` (opt-in): rename an unsuffixed `type: gist|schema|memory`
     page and rewrite every inbound `relates_to` path and relative link in the
     store. Blocked when any `atlas://` text names the page or the page sits in
     an overlay-claimed folder. Stores outside this root are not scanned.
7. **Subject clustering.** The helper groups pages by naming only: the same
   filename stem in two or more folders, an operator-named
   `--subject-folder <folder>:<stem>`, or a page whose `work_id` names an
   existing `work/<work_id>/` folder. Without a safe target it is a `report`.
   A move is `confirm` only when the target folder exists, the filename is
   free, the page is not a gist, schema, or memory page, and no `atlas://` text
   names it. Moves rewrite inbound and outbound links. Layer pages hand off to
   path remember because a move changes schema coverage. Do not detect subject
   change any other way.
8. **Apply.** Only after the operator has seen the task lists. `apply` re-checks
   HEAD and the sha256 of every file each selected task touches. Any change
   since plan means a stale plan: exit 2, nothing written, re-run plan. It
   applies auto tasks, opt-in tasks with `--include-opt-in`, and confirm tasks
   named with `--confirm`. It never applies handoff, report, or blocked tasks.
9. **Verify.** Run `atlas compile --root <root> --dry-run`. Report the exit,
   the remaining findings, and the residual tasks apply printed. Hand handoff
   tasks to path remember or memory-migrate as named. Commit and push follow
   the store's normal remember rules; this path does not push.
10. **Whole-store run.** With target `.`, walk the task lists folder by folder.
    Re-plan after each apply. Stop when only handoff, report, or blocked tasks
    remain.

## Do not invent gist text

A gist description must remain an exact substring of the derived memory body
or description. The only text this path writes into a page is text already in
another page: the memory description, a schema title, or a link path. If no
such text exists, hand off. Do not write a new memory claim.

## Exit receipt

```text
skill: atlas
path: atlas-optimise
root: …
target: …
plan: exit N, tasks per folder
apply: exit N, applied ids | not run (dry-run)
compile: exit N
residual: handoff/report/blocked counts
```

## Non-goals

- Running inside install or compile.
- memory-migrate, contract-file rewrites, or stamp changes.
- A new memory layer, a two-gist rule, or a new compile check.
- Moving stores, cross-store link repair, or pushing.
