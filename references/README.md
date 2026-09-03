# Atlas store lives in its own repository

This skill’s process memory is **not** authored here. Activation path: [`paths/mount.md`](paths/mount.md).

**Remote:** `https://github.com/sergio-sisternes-epam/atlas-atlas`

On a machine with git and Atlas CLI:

```text
atlas auth login --host github.com
atlas mount github.com/sergio-sisternes-epam/atlas-atlas --ref main
```

Default mount = git submodule at `.atlas/github.com/sergio-sisternes-epam/atlas-atlas` (compile/query root)
Git root of the store **is** the OKF root (`SCHEMA.json`). Do not mount at `references/atlas`.

## CI for Atlas mounts

Use path `ci` (`paths/ci.md`) to assess, install, or repair the canonical
compile gate on any mount repository containing `SCHEMA.json`.

- `ci/github-actions.caller.yml` — preferred thin caller of the reusable
  Atlas workflow.
- `ci/github-actions.compile.yml` — self-contained GitHub Actions fallback.

Both run an unfocused compile, retain warning JSON, and fail on critical
compile issues.
