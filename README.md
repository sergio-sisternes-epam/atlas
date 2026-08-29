# atlas

Durable OKF v0.2 knowledge substrate. Private APM package (`SKILL.md` + `apm.yml` at repo root). Format authority remains **okf**.

```text
apm install sergio-sisternes-epam/atlas
```

Process memory is **not** in this repo. Do not add `references/atlas/` here. Canonical store:

https://github.com/sergio-sisternes-epam/atlas-atlas

OKF root inside that repo is `atlas/` (`atlas/SCHEMA.json`), not git root.

```text
atlas mount github.com/sergio-sisternes-epam/atlas-atlas --ref main
```

Default clone path: `.atlas/github.com/sergio-sisternes-epam/atlas-atlas`  
Compile/query root: `.atlas/github.com/sergio-sisternes-epam/atlas-atlas/atlas`

See `SKILL.md` and `apm.yml`.
