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

   Generic GitHub token variables apply only to `github.com` and `*.ghe.com`.
   GHES environment credentials require an exact `GH_HOST` match. An unmatched
   host uses anonymous HTTPS with credential helpers disabled; use `--ssh` or
   `gh auth login --hostname <host>` for private repositories.

   A completely empty remote is a valid new-Atlas mount. Because Git cannot
   register a submodule without a commit, `atlas mount` creates a deterministic
   local empty bootstrap commit on `ref`, registers the gitlink, and leaves the
   remote untouched. Continue through path `init` before committing the
   consumer repository. A non-empty remote that lacks `ref` still fails; Atlas
   does not create a divergent branch. Failed mounts roll back the target,
   submodule metadata, index, and local Git configuration.

   Mesh `strategy` is preserved on remount. Missing `strategy` means **dedicated**.
   Shared mounts track `.gitmodules` `branch = atlas` (do not leave the nested
   checkout detached). Same-repo shared submodules duplicate the git object
   store on recursive clone; that is accepted.

3. Set card `root` to the resolve path. **Use skill atlas** with that `--root` (recall, remember, work, landscape).

Page pointers may be floating (`atlas://<host>/<org>/<repo>/<path>[#fragment]`)
or pinned (`atlas://<host>/<org>/<repo>/<path>@<commit>[#fragment]`), where
`commit` is exactly 40 lowercase hexadecimal characters and the path is
nonempty. A host may include a port. The fragment is opaque.
Compile reports malformed pin-like suffixes as critical and checks mounted
pins locally without fetching: missing commits or paths in a complete clone
are critical, while shallow or unmounted stores remain unverifiable warnings.
Floating pointers continue to resolve at the mounted tip. `atlas resolve`
refuses a pin unless `--tip` is supplied; that option returns a result labelled
`tip`, not the cited historical content. Use `atlas link show <pinned-uri>` to
read the cited version and compare it with the mounted tip; `--show` includes
capped cited text and `--diff` includes a capped path-scoped diff.
`atlas link pin <floating-uri-or-path>` creates a pin to the mounted tip.

Do not write into the calling skill package. This file is not a store.
