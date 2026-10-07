---
name: atlas/paths/atlas-optimise
description: Use this path only when the operator explicitly asks to optimise an Atlas target (one folder or the store root). It fills upper layers from evidence and tidies the four-layer discipline, with a per-folder task list and a dry-run first. Trigger on atlas-optimise, optimise this atlas, fill gists, tidy layers, consolidate folders, dream phase, finish the layers, fix dead frame cues. Not on install. Not on compile. Expensive and scales with the chosen target. Not a separate package. Sleep and consolidate are not this path.
path_id: atlas-optimise
---

# Path: atlas-optimise

Not a separate package. Not a memory layer.

Optimise is the operator-run interim content-fill toward a future offline dreamer. Remember stays the awake writer of new claims. Sleep and consolidate are not implemented.

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
target: <folder inside root> | .     # still required
optimise_mode: full | custom | incremental | path   # default path
since_hours: <positive int>          # incremental default 24; committer clock
custom_tree: <path>|…                # required when optimise_mode=custom
tidy_only: true | false              # true = tidy repairs only
auto_verbatim: true | false          # opt-in; confirm stays the default
fill_sensible: true                  # default posture; not a force-all completeness mode
phase: plan | apply
pilot: true | false                  # receipt only; does not authorize fleet
cost_ceiling: <pages>                # default 200 pages examined
```

Then read this file. A missing target means Enter is incomplete: ask the
operator for one. Do not assume the store root.

Use exactly one primary mode. Path is the default and fills by default inside
`--target`. Full requires `target: .` so a whole-store run is never
accidental, and Full is serial only: do not start a second Full on any store
until the first has finished. Custom requires at least one `--custom-tree`
path prefix. Incremental reads git commit history for the last 24 hours
unless `since_hours` says otherwise, using the committer clock. Dirty and
uncommitted parents are excluded from fill. Incremental may be narrowed by
`--target` or by `--custom-tree`. Combining `--custom-tree` or `--since-hours`
with path or full is a refusal.

## Locked model this path enforces

The four-layer walk is optional progressive disclosure. Recall may walk index,
then schema, then gist, then memory, and it may stop early. `index.md` is a
cue list, not content. An index may exist with or without a schema. A memory
or any other type may sit in the index with no gist and no typed middle
extension. Non-memory types stay index-first-class: this path does not force
them through a gist or a schema.

When a gist is created, that gist forces one same-folder schema. A second
schema is legal when the subject changes. A folder with zero gists needs no
schema. `hub.md` is not a memory layer. Suffixes `.schema.md`, `.gist.md`,
`.memory.md` are search handles; frontmatter `type` is authoritative. Compile
fails only on a gist with no schema, a schema missing from index, or a stale
upper page. A residual `missing_gist` is info by default and is not a fleet
completeness bar. This path adds no compile check.

## Helper

```bash
python3 <atlas-skill>/scripts/atlas_optimise.py plan  --root <root> --target <folder|.> --out-dir <dir outside the store> [--optimise-mode path|full|custom|incremental] [--since-hours <N>] [--custom-tree <prefix>]... [--tidy-only] [--auto-verbatim] [--fill-sensible] [--cost-ceiling <pages>] [--pilot] [--subject-folder <folder>:<stem>]...
python3 <atlas-skill>/scripts/atlas_optimise.py apply --root <root> --target <folder|.> --plan <out-dir>/plan.json [--include-opt-in] [--confirm <task-id>]...
```

The helper is standalone. `atlas.py` has no optimise command and nothing in
install, init, compile, or memory-migrate calls it. It never writes
`CONTRACT.json` or `SCHEMA.json`. Exit codes: plan 0 no tasks, 1 tasks listed,
2 refused. apply 0 no residual tasks, 1 residual tasks, 2 refused with nothing
written. A residual `missing_gist` left because evidence was insufficient is
not a refusal and does not fail the run.

## Procedure

1. Stop unless this path was explicitly chosen. Not on install. Not on compile.
2. Confirm the target and the mode. Cost scales with scope. Full reads the
   whole store and is serial only. The default cost ceiling is 200 pages
   examined; a plan over the ceiling is refused.
3. **Plan (dry-run, always first).** Run `plan` with `--out-dir` outside the
   store. It writes nothing in the store and refuses an out-dir inside it. It
   writes `plan.json`, `receipt.json`, and one migration task list per top-level folder
   (`tasks/<folder>.md`, `tasks/root.md` for root files).
   Show the operator the task lists before any apply. The receipt records
   fetch OK, the git tip, counts, residuals, the security scan, and cost
   against the ceiling.
4. **Precondition.** If the plan has a `contract-precondition` task (the store
   still uses `SCHEMA.json`, or has `type: frame` pages), every other task is
   blocked. Do not run memory-migrate from here. The operator may choose path
   memory-migrate `--batch contract-file`; then re-run plan.
5. **Do not stop early.** Pages that already share a parent are not a reason
   to stop. Dead `frame.md` cues and gist descriptions missing from the memory
   above them are the work. Read every folder's list.
6. **Fill tasks** (evidence-gated; skipped entirely with `--tidy-only`):
   - `missing-gist-fill`: an eligible parent has no gist. Eligible parents are
     every compile missing-gist type (`experience`, `decision`, `lesson`,
     `recipe`, `document`, `memory`, `page`), not memory alone. Fill is
     evidence-gated (`--fill-sensible` names this default). It does not force
     a gist onto every indexed page. Same-folder peers that already
     `relates_to` each other, or that share a `work_id`, get one shared useful
     gist whose `derived_from` lists all of them. Cross-folder `relates_to`
     does not join a cluster. Unrelated pages in one folder stay separate
     clusters. Confirm by default. Auto only when `--auto-verbatim` is set and
     the description is a verbatim parent description or the first claim line.
     Insufficient evidence is handoff, including a thin peer covered only
     because a same-folder neighbour had evidence. No titled stub. Restricted
     sensitivity and secret-class text are blocked and are not copied into the
     plan. A medium `booking_manage_reference` is handoff, not an applied gist.
   - `gist-body-enrich`: a gist description is missing or is not a substring
     of its parent, and the parent has an evidence pack. Same confirm / auto
     rule. The tidy `stale-gist-description` copy stays in place when it
     already applies.
   - `schema-fill` (confirm): a folder has at least one gist and no schema.
     The body is minimal prose cited from gist titles and descriptions, plus
     `relates_to`. It is not a title alone and not a rich essay. Too-thin
     evidence is handoff.
7. **Tidy repairs** (each task names its class):
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
8. **Subject clustering.** The helper groups pages by naming only: the same
   filename stem in two or more folders, an operator-named
   `--subject-folder <folder>:<stem>`, or a page whose `work_id` names an
   existing `work/<work_id>/` folder. Without a safe target it is a `report`.
   A move is `confirm` only when the target folder exists, the filename is
   free, the page is not a gist, schema, or memory page, and no `atlas://` text
   names it. Moves rewrite inbound and outbound links. Layer pages hand off to
   path remember because a move changes schema coverage. Do not detect subject
   change any other way.
9. **Apply.** Only after the operator has seen the task lists. `apply` re-checks
   HEAD and the sha256 of every file each selected task touches, including
   every evidence-pack source. Any change since plan means a stale plan: exit
   2, nothing written, re-run plan. It applies auto tasks, opt-in tasks with
   `--include-opt-in`, and confirm tasks named with `--confirm`. It never
   applies handoff, report, or blocked tasks. It scans again before writing
   and refuses if a selected task would promote secret-class or restricted
   text. It never edits parent claim text.
10. **Verify.** Run `atlas compile --root <root> --dry-run`. Report the exit,
    the remaining findings, and the residual tasks apply printed. Hand handoff
    tasks to path remember or memory-migrate as named. Commit and push follow
    the store's normal remember rules; this path does not push.
11. **Whole-store run.** With target `.`, walk the task lists folder by folder.
    Re-plan after each apply. Stop when only handoff, report, or blocked tasks
    remain. One Full at a time.

## Do not invent gist text

A gist description must remain an exact substring of a derived parent body
or description. For one parent, that parent must contain it. For a shared
gist, at least one `derived_from` parent must contain it. Fill writes a
description only when the evidence pack names that substring (the parent
description, or the first claim line). Schema prose cites gist titles and
descriptions already on disk, and only once a gist exists. If no such text
exists, hand off. Do not write a new parent claim. Do not write a title-only
stub to clear `missing_gist`. Do not promote secrets, payment or identity
numbers, a `booking_manage_reference`, or `sensitivity: restricted` text into
an upper page.

## Pilot before any fleet claim

Do not say a store is ready for fleet, or run Full across stores, until a
pilot receipt and a quality check exist. Start with one subject, Path or
Incremental, then a heavier Path or Incremental pilot, and only then Full.
Full stays serial.

The check is:

- Fidelity: every auto-written gist description is a verbatim substring of its
  parent, and there are zero parent edits.
- Harm: no critical regress on untouched paths, no unexpected parent diffs, no
  contract writes.
- Coverage: `missing_gist` drops only when an evidence-backed apply wrote the
  gist. A residual `missing_gist` with insufficient evidence is expected.
- Spot-check: the operator reads N=10 filled gists.
- Security scan: zero new critical or high secret-class findings on touched
  paths.
- Disagreement rate on confirm tasks is informational. It is not a fail gate.

The receipt's `fleet_ready` field stays false. This path does not authorize
fleet apply.

## Exit receipt

```text
skill: atlas
path: atlas-optimise
root: …
target: …
optimise_mode: …
fetch_ok: true | false
tip: <git HEAD or none>
plan: exit N, tasks per folder
apply: exit N, applied ids | not run (dry-run)
compile: exit N
residual: handoff/report/blocked counts; missing_gist is not a failure
security: pass | blocked
cost: projected pages / ceiling
spot-check: N=10 operator
```

The helper writes the same fields to `receipt.json` (plan) and
`receipt-apply.json` (apply) next to the plan, outside the store.

## Done when (day one)

Day one is fill-when-sensible plus tidy for the locked scope: useful gists
for compile missing-gist types when evidence supports them, schema pages as
minimal prose when a gist is created, Path fill by default, Incremental on a
24 hour committer window, a security scan on plan and apply, a cost ceiling,
and a durable receipt with fetch OK and tip. Receipt rows for fills that
happen include `scan_gate_refuse_count`, `body_fills`, `shared_gist_count`,
`cluster_size_hist`, `enrich_optional_count`, and `zero_crit_high_promoted`.
Hits are `{path, type, severity}` only. Residual `missing_gist` after a
handoff is still done. Sleep is not done.

## Non-goals

- Running inside install or compile.
- memory-migrate, contract-file rewrites, or stamp changes.
- A new memory layer, a two-gist rule, or a new compile check.
- Implementing sleep or consolidate.
- Editing parent claim text, or inventing gist or schema prose.
- Moving stores, cross-store link repair, or pushing.
- Parallel Full across stores.
