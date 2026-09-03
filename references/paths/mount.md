---
name: atlas/paths/mount
description: Mount-if-missing any Atlas named on the card, then use skill atlas. Not a store.
path_id: mount
---

# Path: mount

Generic. `atlas_id` and `ref` come from the Enter card. Missing `atlas_id` ⇒ incomplete Enter.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: mount
path_module: references/paths/mount.md
intent: <one line>
atlas_id: <host/org/repo>
ref: <branch>
root: <set after resolve>
```

## Procedure

1. No git repo: **stop**. Do not mount. Do not persist.
2. **Mount-if-missing** (no `--target`; submodule at `<git-root>/.atlas/<atlas_id>/`):

   ```text
   python3 <atlas-skill>/scripts/atlas.py mount <atlas_id> --ref <ref>
   python3 <atlas-skill>/scripts/atlas.py resolve <atlas_id>
   ```

3. Set card `root` to the resolve path. **Use skill atlas** with that `--root` (query, remember, work, landscape).

Do not write into the calling skill package. This file is not a store.
