---
title: landscape
description: Research competitors and partners on demand and update the living comparison memory in an Atlas store.
sidebar:
  order: 12
source:
  - references/paths/landscape.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/landscape.md: 71c955179020dea09620cc688514bf9fb3a8eaa2
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `landscape` module runs on-demand deep research on competitors and *symbionts* (possible partners).
It updates the store's living comparison memory.
It also owns the landscape *protostars*.
A protostar is a half-formed or unverified page that may grow into a full page later.

## When

Use `landscape` when you ask the agent to:

- refresh the landscape,
- update competitors,
- find partners or symbionts, or
- run a comparison review.

You do not have to name targets. The agent finds them.

## What it does

1. The agent resolves the store root, the same way as [`recall`](/atlas/modules/recall/).
2. The agent reads the current frame and the dead frame first.
   The current frame is the vision page, the comparison page, the competitors page, the partner pages, the glossary and the landscape protostars.
   The dead frame is the set of terminated exit pages.
   The agent does not treat terminated pages as the current identity.
3. The agent does deep research itself. It does not wait for a target list.
   - It researches each living class on the comparison and competitors pages.
   - Then it researches new candidates that the search finds.
   - It stops when every class has a sourced note, and every new name is living, a protostar, terminated or an explicit gap.
4. The agent classifies each name with a glossary label: `rival`, `neighbour`, `projector`, `symbiont` or `out-of-frame`.
5. The agent writes comparison memory:
   - `rival` and `neighbour` go to the competitors page.
   - `projector` and `symbiont` go to a partner page in the partners folder, with a `role` and the label.
   - Half-formed or unverified names become a protostar in the landscape folder.
     The protostar has `star_kind` set, `kva: forming` and `growth: true`.
   - If a name is an identity risk (an out-of-frame name treated as a peer), the agent does not add the row.
     It loads the `terminate` path of the companion skill `discuss`.
6. The module owns its protostars. It can create, update or promote them, or request terminate.
   Ownership ends when someone opens a research or [`work`](/atlas/modules/work/) hub on that name.
   Then the protostar `follows` that work, and this module stops changing it as owner.
7. **Cite or gap.** Every living claim needs `origin` or `sources`, or an explicit gap line.
   The agent does not invent capabilities.
8. **Job test.** The agent does not count features.
   It asks: can a second team mount, branch, open a pull request and compile?
9. **Compile green.** The agent runs compile and needs exit 0:

   ```text
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```

10. The agent appends to `log.md` only for structural adds.
    Examples are a new partners or landscape folder, or the first promote of the glossary.

## How to ask for it

Ask in plain words, for example "refresh the landscape", "update competitors" or "who should we partner with?".
You may add extra names. They are additive only: the agent still runs the full research.
To learn about the module without running it, ask `/atlas help landscape`.

## Activation card

The agent renders the card as a fenced `text` block. The `landscape` card has these fields:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: landscape
path_module: references/paths/landscape.md
intent: refresh catalogue and/or symbiosis
root: <atlas store root>
```

`root` is the store root that [`mount`](/atlas/modules/mount/) resolved.

## Boundaries

- You do not need to give a target list.
- The module does not build feature-matrix leaderboards.
- It is not a second keep, vary and abandon implementation. It uses the `discuss` skill's `terminate` path instead.
- It does not run on a schedule.

:::note
If you explicitly kill a comparison or thesis, the agent loads the companion skill `discuss` and uses its `terminate` path.
If `discuss` is not available, the agent stops and tells you.
:::

## Related CLI commands

- [`compile`](/atlas/reference/cli/compile/)

## Related modules

- [`mount`](/atlas/modules/mount/) sets `root` first.
- [`recall`](/atlas/modules/recall/) resolves the root the same way.
- [`work`](/atlas/modules/work/) takes over a protostar when a work hub opens on its name.
