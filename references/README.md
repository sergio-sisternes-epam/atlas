# Atlas store lives in its own repository

This skill’s process memory is **not** authored here. It is mounted from `atlas-atlas` as the `references/atlas` submodule.

**Remote:** `https://github.com/sergio-sisternes-epam/atlas-atlas`

On a machine with git and Atlas CLI:

```text
atlas auth login --host github.com
atlas mount github.com/sergio-sisternes-epam/atlas-atlas --ref main --target references/atlas
```

Mount path: `references/atlas`  
OKF root is `atlas/` inside the store repo (`atlas/SCHEMA.json`), not git root.  
Compile/query root: `references/atlas/atlas`

