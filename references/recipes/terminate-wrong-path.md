---
name: atlas/recipes/terminate-wrong-path
description: When the user kills a frame during remember or query, or explicitly cancels an atlas-tasks task (not a duplicate), load discuss path terminate. Do not re-implement KVA here.
---

# Recipe: terminate a wrong path

## Trigger (explicit only)

User says the current comparison, thesis, or branch is wrong. Examples: “wrong comparison”, “that is not what Atlas is”, “terminate this branch”, “KVA terminate”.

When the user explicitly asks in this turn to cancel an atlas-tasks task (not a duplicate) because its goal failed, was declined or is out of scope (atlas-tasks update path, step 8a), that request is the explicit trigger for the cancelled task's own pages. Run terminate once per subject: the task pointer, then its body page, each as the single `subject_node`, with the same `living_node` (the page holding the standing answer). The second run reuses the exit-reason node the first wrote. A duplicate cancel, a task marked done, or a cancel the user did not ask for is not a trigger.

Model disagreement alone is not a trigger.

## Do

1. Identify `subject_node` (the frame being killed) and `living_node` (vision or correct thesis). If the living page does not exist, you will create it under terminate, not as a silent extra remember dump.
2. Load catalog skill **discuss** by name (full `SKILL.md`).
3. Load `discuss/references/paths/terminate.md`.
4. Follow that path on this Atlas `root`.
5. If the live branch now has a different subject, use Atlas **remember** to
   add `<name>.schema.md`, link it same-level to the prior schema, and list it
   from the folder `index.md`. Keep `hub.md` in place; it is a work hub, not a
   memory level.
6. After compile green, answer only from living pages and the exit-reason node. Do not continue the dead matrix.

## Do not

- Delete the wrong branch.
- Flip `kva: terminated` back to `forming` on the same page.
- Copy KVA rules into this recipe.
- Terminate during an ordinary remember of an experience that happens to mention an old idea.
