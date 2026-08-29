# Atlas store lives in its own repository

This skill’s process memory is **not** authored here any longer as the source of truth.

**Remote:** `https://github.com/sergio-sisternes-epam/atlas-atlas`

On a machine with git and Atlas CLI:

```text
atlas auth login --host github.com
atlas mount github.com/sergio-sisternes-epam/atlas-atlas --ref main
```

Default mount path: `.atlas/github.com/sergio-sisternes-epam/atlas-atlas`  
OKF root is the repository root (`SCHEMA.json` at the top of `atlas-atlas`).

This Grok session cannot keep a clone after publishing. Until you mount on a git machine, a local working copy may still exist under `references/atlas/` for the running skill. Treat GitHub as the published snapshot.
---
