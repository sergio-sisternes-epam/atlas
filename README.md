# atlas

Durable OKF v0.2 knowledge substrate. Private APM package (`SKILL.md` + `apm.yml` at repo root). Format authority remains **okf**.

```text
apm install sergio-sisternes-epam/atlas
```

Process memory is **not** authored here. Canonical store:

https://github.com/sergio-sisternes-epam/atlas-atlas

Git root **is** the OKF root (`SCHEMA.json`). Mount it at `references/atlas`:

```text
atlas mount github.com/sergio-sisternes-epam/atlas-atlas --ref main --target references/atlas
```

Mount path = compile/query root: `references/atlas`

See `SKILL.md` and `apm.yml`.

## Panel review

The project-level panel review skill is authored at
`.apm/skills/panel-review/`. Generate the Copilot deployment with:

```text
apm install --target copilot
```

APM deploys it to `.agents/skills/panel-review/`. Edit the `.apm/` source,
not the generated copy.
