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

## Code review panel

The project-level `code-review` skill is the broad pull-request review
entrypoint. It requires the sibling `panel-review` skill to run the cost-aware
multi-lens review and publish its findings. Both are authored under
`.apm/skills/`. Generate the Copilot deployment with:

```text
apm install --target copilot --frozen
```

APM deploys both skills under `.agents/skills/`. Edit the `.apm/` sources, not
the generated copies.

GitHub documents `code-review` as the review-focused directory name that makes
Copilot code review load a skill. GitHub does not document skill-to-skill
execution as guaranteed, so this adapter fails closed if it cannot load or
execute `panel-review`.
