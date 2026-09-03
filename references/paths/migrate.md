---
name: atlas/paths/migrate
description: Move a skill off vendor store at references/atlas onto .atlas/<id>/ via path mount. One own store per Run.
path_id: migrate
---

# Path: migrate

Generic. For any skill that still vendors process memory at `<skill>/references/atlas`. Do **not** copy this file, `mount.md`, or `init.md`. Requires Atlas 0.8.11+. `atlas_id` comes from the card (from that skill’s `.gitmodules` url as `host/org/repo`). Missing `atlas_id` ⇒ incomplete Enter.

Leave other subjects’ `<subject>/references/atlas/` until those skills run this path.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: <skill>
path: migrate
path_module: references/paths/migrate.md
intent: <one line>
atlas_id: <host/org/repo>
ref: main
```

## Procedure

1. Load path **mount** with the same `atlas_id` and `ref`. Query/remember use `--root` from `atlas resolve <atlas_id>`. No git repo: refuse persist.
2. Move the gitlink from `references/atlas` to `.atlas/<atlas_id>/`. Same path in `atlas-mesh.json`. Delete `.gitignore` `.atlas/` if present.
3. Replace every `atlas mount … --target references/atlas` and every `--root` that pointed at the skill tree (SKILL, README, path modules, workflow checklists, run receipts, construct smokes that assert the gitlink path).
4. Remove the skill-package store at `references/atlas` (submodule and empty `.gitmodules` row).
5. New Atlas later: path **init**, existing `remote` only. Never `gh repo create`.
6. Writes: two PRs — store repo, then parent gitlink bump.

Do not add a skill-side `references/atlas.md` pointer.
