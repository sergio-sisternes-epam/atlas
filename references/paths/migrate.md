---
name: atlas/paths/migrate
description: Relocate references/atlas onto .atlas/<id>/, or move store history between shared and dedicated strategy. One own store per Run.
path_id: migrate
---

# Path: migrate

Generic. Card **migrate_mode is required**. Missing `migrate_mode` ⇒ incomplete Enter.

- `relocate` — move a skill off vendor store at `references/atlas` onto `.atlas/<id>/` via path mount.
- `strategy` — push store git history to the other storage strategy (shared ↔ dedicated). Do **not** use CLI `atlas migrate` (that copies into `staging/`).

Do **not** copy this file, `mount.md`, or `init.md`. Requires Atlas 0.11.0+. For relocate, `atlas_id` comes from the card (from that skill’s `.gitmodules` url as `host/org/repo`). Missing `atlas_id` on relocate ⇒ incomplete Enter.

Leave other subjects’ `<subject>/references/atlas/` until those skills run relocate.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: <skill>
path: migrate
path_module: references/paths/migrate.md
intent: <one line>
migrate_mode: relocate | strategy
atlas_id: <host/org/repo>
ref: main
destination_strategy: shared | dedicated
remote: <existing dedicated URL when destination is dedicated>
```

`destination_strategy` is required when `migrate_mode` is `strategy`. Same source and destination strategy ⇒ fail closed.

## Procedure

### migrate_mode: relocate

1. Load path **mount** with the same `atlas_id` and `ref`. Query/remember use `--root` from `atlas resolve <atlas_id>`. No git repo: refuse persist.
2. Move the gitlink from `references/atlas` to `.atlas/<atlas_id>/`. Same path in `atlas-mesh.json`. Delete `.gitignore` `.atlas/` if present.
3. Replace every `atlas mount … --target references/atlas` and every `--root` that pointed at the skill tree (SKILL, README, path modules, workflow checklists, run receipts, construct smokes that assert the gitlink path).
4. Remove the skill-package store at `references/atlas` (submodule and empty `.gitmodules` row).
5. New Atlas later: path **init**, existing `remote` only. Never `gh repo create`.
6. Writes: two PRs — store repo, then parent gitlink bump.

Do not add a skill-side `references/atlas.md` pointer.

### migrate_mode: strategy

1. Read mesh `strategy` (missing = dedicated). Do not infer from id+ref when the field is present.
2. Destination needs an **existing** git remote when `destination_strategy` is dedicated. Never create a host repository.

   ```text
   python3 <atlas-skill>/scripts/atlas.py store rehost --destination-strategy <shared|dedicated> [--remote <url>] --json
   ```

3. History is pushed (fast-forward only). Unrelated destination history ⇒ fail closed. No page-import rewrite. No dual-write: the old mount is removed after the new gitlink exists.
4. Mesh `id` / `ref` / `strategy` match the destination. Shared dest: `ref` is `atlas`; then GitHub driver (do not strip rulesets on the reverse).
5. Compile green on the new root. Do not write the old root.
