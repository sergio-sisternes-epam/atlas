# Atlas store lives in its own repository

This skill’s process memory is **not** authored here. Do not add `references/atlas/` or any process-memory tree to this repo.

**Remote:** `https://github.com/sergio-sisternes-epam/atlas-atlas`

On a machine with git and Atlas CLI:

```text
atlas auth login --host github.com
atlas mount github.com/sergio-sisternes-epam/atlas-atlas --ref main
```

Default clone path: `.atlas/github.com/sergio-sisternes-epam/atlas-atlas`  
OKF root is `atlas/` inside the store repo (`atlas/SCHEMA.json`), not git root.  
Compile/query root: `.atlas/github.com/sergio-sisternes-epam/atlas-atlas/atlas`

