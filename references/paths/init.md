---
name: atlas/paths/init
description: Scaffold a new Atlas in the active git repo. Default storage strategy is shared (consumer atlas branch). Never creates the remote repository.
path_id: init
---

# Path: init

Generic. For any skill or session that needs a **new** Atlas. Default **strategy is shared**. This path never creates a git host repository.

**Embedded** still means a skill-package store at `references/atlas` (path **migrate**). Storage strategy is `shared` | `dedicated`.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: init
path_module: references/paths/init.md
intent: <one line>
strategy: shared | dedicated
remote: <consumer origin, or existing dedicated store URL>
atlas_id: <host/org/repo, or set after id>
root: <set after resolve>
```

`strategy` defaults to **shared** when omitted. If `strategy` is dedicated and `remote` is missing: **ask** for an existing store remote and **stop**. Do not invent one. Do not `gh repo create` or any host API create.

## Procedure

1. No git repo in the session: **stop**.
2. Shared (default): `remote` is the consumer origin if omitted. Dedicated: `remote` is an **existing** store repository.

   ```text
   python3 <atlas-skill>/scripts/atlas.py store init --strategy <shared|dedicated> [--remote <url>] --json
   python3 <atlas-skill>/scripts/atlas.py resolve <atlas_id>
   ```

   CLI `atlas init --root` only writes SCHEMA files. Store bootstrap is `atlas store init`.
3. **shared:** creates or reuses branch `atlas` on the consumer. Missing branch → empty orphan tree, then SCHEMA (not a copy of the default branch). Existing `atlas` without `SCHEMA.json` → fail closed. Mesh `id` is the consumer, `ref` is `atlas`, `strategy` is `shared`. `.gitmodules` records `branch = atlas`. Then the GitHub driver (ruleset blocking direct push) if the host is GitHub; self-hosted prints a warning and continues. Push the empty `atlas` branch **before** the ruleset so the first push is not blocked.
4. **dedicated:** mount that existing remote (today’s path). Never create the host. Mesh `strategy` is `dedicated`. Missing mesh `strategy` on older files is also dedicated.
5. If clone/mount fails because the remote does not exist: tell the human to create the repository themselves, then retry. Do not create it.
6. Set card `root`. Further query/persist is skill atlas on that root.

Same-repo submodule (shared) clones the consumer git object store twice on `--recursive`. Accept that cost; do not switch to worktree.

Do not write the new store into a skill package. Do not `--target references/atlas`.
