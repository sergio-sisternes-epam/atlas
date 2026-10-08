---
title: atlas-optimise
description: Fill and tidy the memory layers of a named target, with a dry-run plan before any apply.
sidebar:
  order: 10
source:
  - references/paths/atlas-optimise.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/atlas-optimise.md: 6add480ffa36b5874039dc9e841add4843ed8a85
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `atlas-optimise` module fills and tidies the four memory layers of one target.
The target is one folder or the whole store root.
The operator chooses it. The agent never runs it on install or compile.
It is not a separate package and it is not a memory layer.

Atlas uses four optional layers.
The *index* (`index.md`) is a cue list. A *schema* summarises a folder. A *gist* summarises one or more memory pages. A *memory* holds the full claim.
`atlas-optimise` adds missing gists and schemas when evidence supports them, and repairs broken layer links.
The [`remember`](/atlas/modules/remember/) module stays the writer of new claims.

:::note
`atlas-optimise` is an interim, operator-run fill step toward a future offline process.
Sleep and consolidate are **not implemented**. This module does not provide them.
:::

## When

Use `atlas-optimise` only when you explicitly choose it and name a target.
The agent never selects it from install, compile, init or memory-migrate.

The run is expensive. Cost grows with the target size.
The default cost ceiling is 200 pages examined. The helper refuses a plan over the ceiling.

## What it does

The module uses a standalone helper, [`atlas_optimise.py`](/atlas/reference/cli/atlas-optimise-script/).
`atlas.py` has no optimise command.
The helper never writes the store contract file (`CONTRACT.json` or `SCHEMA.json`).

1. **Confirm.** The agent stops unless you chose this module. It confirms the target and the mode.
2. **Plan (dry-run, always first).** The agent runs `plan` with an output folder outside the store:

   ```text
   python3 <atlas-skill>/scripts/atlas_optimise.py plan --root <root> --target <folder|.> --out-dir <dir outside the store>
   ```

   `plan` writes nothing in the store. It writes `plan.json`, `receipt.json` and one task list per top-level folder.
   The receipt records fetch status, the git tip, counts, residuals, the security scan and cost against the ceiling.
   The agent shows you the task lists before any apply.
3. **Precondition.** If the store still uses `SCHEMA.json` or has `type: frame` pages, the plan has a `contract-precondition` task.
   This task blocks all other tasks. The agent does not run memory-migrate from here.
   You may choose the [`memory-migrate`](/atlas/modules/memory-migrate/) module and then re-run the plan.
4. **Read every list.** The agent does not stop early. Dead index cues and stale gist descriptions are the work.
5. **Apply.** Only after you have seen the task lists:

   ```text
   python3 <atlas-skill>/scripts/atlas_optimise.py apply --root <root> --target <folder|.> --plan <out-dir>/plan.json [--include-opt-in] [--confirm <task-id>]...
   ```

   `apply` re-checks the git HEAD and the hash of every file a selected task touches.
   Any change since the plan makes the plan stale: exit 2, nothing written, re-run the plan.
   `apply` writes `receipt-apply.json` next to the plan, outside the store.
6. **Verify.** The agent runs the `compile` command with `--dry-run`:

   ```text
   python3 <atlas-skill>/scripts/atlas.py compile --root <root> --dry-run
   ```

   It reports the exit code, remaining findings and residual tasks.
   It passes handoff tasks to `remember` or `memory-migrate`. The module does not push.
7. **Whole store.** With target `.`, the agent walks the task lists folder by folder and re-plans after each apply.
   It stops when only handoff, report or blocked tasks remain.

### Modes

Use exactly one mode. `path` is the default.

- `path` fills inside `--target`.
- `full` needs `target: .`, so a whole-store run is never an accident. Run only one `full` at a time, on any store.
- `custom` needs at least one `--custom-tree` path prefix.
- `incremental` reads git commits from the last 24 hours (committer clock), or from `--since-hours`. Dirty and uncommitted parents are not filled.

Using `--custom-tree` or `--since-hours` with `path` or `full` is refused.

### Task classes

Each task is `auto`, `confirm`, `opt-in`, `handoff`, `report` or `blocked`.
`apply` runs auto tasks, opt-in tasks with `--include-opt-in` and confirm tasks named with `--confirm`.
It never applies handoff, report or blocked tasks.

- **Fill** (skipped with `--tidy-only`): `missing-gist-fill`, `gist-body-enrich` and `schema-fill`.
  Fill is gated on evidence. Fill tasks are confirm by default. A fill is auto only with `--auto-verbatim` and verbatim text.
  Related same-folder pages can share one gist that lists all of them in `derived_from`.
- **Tidy**: `dead-index-cue`, `schema-index-cue`, `uncovered-gist`, `dead-schema-member`, `stale-gist-description`, `layer-skip-cue` and the opt-in `layer-suffix` rename.
- **Subject clustering**: the helper groups pages by naming only, for example the same file name in two folders or a `--subject-folder <folder>:<stem>`.
  A move is confirm only when it is safe. Otherwise it is a report. Layer pages pass to `remember`.

### Exit codes

- `plan`: 0 no tasks, 1 tasks listed, 2 refused.
- `apply`: 0 no residual tasks, 1 residual tasks, 2 refused with nothing written.

A residual `missing_gist` with too little evidence is not a refusal and does not fail the run.

## How to ask for it

Ask with words such as "optimise this atlas", "fill gists", "tidy layers", "finish the layers" or "fix dead frame cues".
Always name a target folder, or `.` for the store root.
To learn about the module without running it, ask `/atlas help atlas-optimise`.

## Activation card

The agent renders the card as a fenced `text` block. The `atlas-optimise` card has these fields:

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

`target` is required. If it is missing, the agent asks you for one. It does not assume the store root.
`custom_tree` is required when `optimise_mode` is `custom`.

## Boundaries

- **Do not invent gist text.** A gist description must be an exact substring of a parent page. Schema prose cites gist titles and descriptions already on disk.
  With no such text, the task is handoff. No title-only stubs.
- The module never edits parent claim text.
- It never promotes secrets, payment or identity numbers, a `booking_manage_reference` or `sensitivity: restricted` text into an upper page. A security scan runs on plan and on apply.
- It does not run inside install or compile.
- It does not run memory-migrate, rewrite contract files or change stamps.
- It adds no new memory layer, no two-gist rule and no new compile check.
- It does not implement sleep or consolidate.
- It does not move stores, repair cross-store links or push.
- It does not run `full` in parallel across stores.

### Pilot before wider rollout

Do not call a store ready for wider rollout until a pilot receipt and a quality check exist.
Start with one subject in `path` or `incremental` mode, then a heavier pilot, and only then `full`.
The check covers fidelity (verbatim gists, zero parent edits), harm, coverage, an operator spot-check of 10 filled gists and the security scan.
The receipt's `fleet_ready` field stays false. This module does not authorise wider rollout.

## Related CLI commands

- [`atlas_optimise.py`](/atlas/reference/cli/atlas-optimise-script/)
- [`compile`](/atlas/reference/cli/compile/)

## Related modules

- [`remember`](/atlas/modules/remember/) writes new claims and takes handoff tasks.
- [`memory-migrate`](/atlas/modules/memory-migrate/) clears the contract precondition and takes some handoff tasks.
- [`recall`](/atlas/modules/recall/) walks the layers this module fills.
- [`atlas-memorise`](/atlas/modules/atlas-memorise/), [`atlas-recall`](/atlas/modules/atlas-recall/) and [`atlas-forget`](/atlas/modules/atlas-forget/) are the other four-layer modules.
