# atlas

Durable OKF v0.2 knowledge substrate. Private APM package (`SKILL.md` + `apm.yml` at repo root). Format authority remains **okf**.

```text
apm install sergio-sisternes-epam/atlas
```

Process memory is **not** authored here. Canonical store:

https://github.com/sergio-sisternes-epam/atlas-atlas

OKF root inside that repo is `atlas/` (`atlas/SCHEMA.json`), not git root. Mount it as a submodule at `references/atlas`:

```text
atlas mount github.com/sergio-sisternes-epam/atlas-atlas --ref main --target references/atlas
```

Mount path: `references/atlas`  
Compile/query root: `references/atlas/atlas`

See `SKILL.md` and `apm.yml`.
