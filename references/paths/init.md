---
name: atlas/paths/init
description: Scaffold a new Atlas in the active git repo from an existing git remote. Never creates the remote repository.
path_id: init
---

# Path: init

Generic. For any skill or session that needs a **new** Atlas. `remote` comes from the Enter card. This path never creates a git host repository.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: init
path_module: references/paths/init.md
intent: <one line>
remote: <existing git remote URL>
atlas_id: <host/org/repo, or set after id>
ref: main
root: <set after resolve>
```

If `remote` is missing: **ask** for an existing git remote and **stop**. Do not invent one. Do not `gh repo create` or any host API create.

## Procedure

1. No git repo in the session: **stop**.
2. `python3 <atlas-skill>/scripts/atlas.py id <remote>` → `atlas_id` (`host/org/repo`).
3. **Mount** that existing remote (no `--target`):

   ```text
   python3 <atlas-skill>/scripts/atlas.py mount <atlas_id> --ref <ref>
   python3 <atlas-skill>/scripts/atlas.py resolve <atlas_id>
   ```

   If clone/mount fails because the remote does not exist: tell the human to create the repository themselves, then retry. Do not create it.
   A completely empty remote succeeds: mount creates the deterministic local
   bootstrap commit needed to register the submodule, without pushing it.
4. If the mount has no `SCHEMA.json`:

   ```text
   python3 <atlas-skill>/scripts/atlas.py init --root <root>
   ```

5. For an empty remote, commit and push the initialized Atlas from `<root>` on
   `ref` before committing the consumer repository's gitlink. This publishes
   the bootstrap commit and initialized content as one branch history; callers
   must not manually recreate or reinitialize the nested checkout.
6. Set card `root`. Further query/persist is skill atlas on that root.

Do not write the new store into a skill package. Do not `--target references/atlas`.
