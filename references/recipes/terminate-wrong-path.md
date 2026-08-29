---
name: atlas/recipes/terminate-wrong-path
description: When the user kills a frame during remember or query, load discuss path terminate. Do not re-implement KVA here.
---

# Recipe: terminate a wrong path

## Trigger (explicit only)

User says the current comparison, thesis, or branch is wrong. Examples: “wrong comparison”, “that is not what Atlas is”, “terminate this branch”, “KVA terminate”.

Model disagreement alone is not a trigger.

## Do

1. Identify `subject_node` (the frame being killed) and `living_node` (vision or correct thesis). If the living page does not exist, you will create it under terminate, not as a silent extra remember dump.
2. Load catalog skill **discuss** by name (full `SKILL.md`).
3. Load `discuss/references/paths/terminate.md`.
4. Follow that path on this Atlas `root`.
5. After compile green, answer only from living pages and the exit-reason node. Do not continue the dead matrix.

## Do not

- Delete the wrong branch.
- Flip `kva: terminated` back to `forming` on the same page.
- Copy KVA rules into this recipe.
- Terminate during an ordinary remember of an experience that happens to mention an old idea.
