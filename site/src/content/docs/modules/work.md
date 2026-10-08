---
title: work
description: Open, update or close work hubs and keep the work cluster linked.
sidebar:
  order: 11
source:
  - references/paths/work.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/work.md: 1a5d13b624ffa484ff4df3bc7b527c37620bc325
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `work` module manages work hubs in an Atlas store.
A *work hub* is a page with `type: work` that tracks one unit of effort.
Each unit has a `work_id`.
The hub links to the pages that belong to that effort, such as experiences, decisions and plans.
Together, the hub and these pages form a *work cluster*.

## When

Use `work` when you start a unit of effort, update its status or close it.
The agent loads this module before any `work_id` lifecycle change.

## What it does

1. The agent resolves the store root.
2. The agent writes the hub at `work/<work_id>.md`.
   The hub has `type: work`, `work_id`, `title`, `status` and `description`.
   It can add sections for scope, status and outcomes as needed.
3. The agent sets a clear status, for example `draft`, `implementing` or `done`.
   The store schema may add more values.
4. The hub links to its important child pages through `relates_to`.
   It uses `kind: related`, or a tighter kind when that is accurate.
5. Each child page under this effort links back to the hub with `kind: implements`.
   The [`remember`](/atlas/modules/remember/) module adds this link when it writes the child.
6. To close the work, the agent sets `status: done`.
   It links any follow-on work with `related` or `follows`.
   It appends an entry to `log.md`.
7. After material hub edits, the agent runs compile:

   ```text
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```

The module is done when:

- the hub path and status are set, and
- the `compile` command exits 0, and
- `log.md` has an entry on close. An entry on open is optional.

`log.md` is the store log. The agent appends to it only for structural changes, such as a work close.

## How to ask for it

Ask the agent to start, update or close a piece of work, or mention a "work hub".
For example, "open a work hub for this effort" or "close this work hub".
To learn about the module without running it, ask `/atlas help work`.

## Activation card

The agent renders the card as a fenced `text` block. The `work` card has these fields:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: work
path_module: references/paths/work.md
intent: <one line>
root: <atlas store root>
```

`root` is the store root that [`mount`](/atlas/modules/mount/) resolved.

## Boundaries

- The hub is not a full session narrative. A session story is an *experience*, written through [`remember`](/atlas/modules/remember/).
- The module does not search. Use [`recall`](/atlas/modules/recall/) to find pages.
- A work hub is not a memory layer.
  If a live branch changes subject, the hub stays put.

## Related CLI commands

- [`compile`](/atlas/reference/cli/compile/)

## Related modules

- [`mount`](/atlas/modules/mount/) sets `root` first.
- [`remember`](/atlas/modules/remember/) writes child pages and session experiences.
- [`recall`](/atlas/modules/recall/) searches the store.
