# okf

Open Knowledge Format — pure format standard and validator.

Private APM package: `sergio-sisternes-epam/okf`

Grok-native layout: `SKILL.md` and `apm.yml` at the repository root.

## Install

Requires APM CLI and GitHub access to this private repository.

```bash
apm install sergio-sisternes-epam/okf
```

Pin a version when consuming from another project:

```yaml
dependencies:
  apm:
    - sergio-sisternes-epam/okf#v0.2.1
```

See `SKILL.md` and `apm.yml`.

## Process memory (not this repo)

Live knowledge-store operations live in Atlas, not here:

```text
atlas mount github.com/sergio-sisternes-epam/okf-atlas
```

Compile/query root: `.../okf-atlas/atlas` (OKF root is `atlas/SCHEMA.json`, not the git root).

Do not use `okf-wiki` for new process memory. Do not add `references/atlas`, `references/wiki`, or any knowledge store to this package.
