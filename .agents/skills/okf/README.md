# okf

Open Knowledge Format — pure format standard and validator.

Private APM package: `sergio-sisternes-epam/okf`

Grok-native layout: `SKILL.md` and `apm.yml` at the repository root.

## Prerequisites

- APM CLI 0.29.0 or newer.
- Read access to this private repository.

## Install

Install the immutable release tag:

```bash
apm install sergio-sisternes-epam/okf#v0.2.1
```

Declare the same tag when consuming OKF from another APM project:

```yaml
dependencies:
  apm:
    - sergio-sisternes-epam/okf#v0.2.1
```

APM can authenticate with `GITHUB_APM_PAT` or another supported Git credential
source. Give the credential Contents: read access and never commit it.

See `SKILL.md` for the runtime contract and `apm.yml` for package metadata.

## Process memory (not this repo)

Live knowledge-store operations live in Atlas, not here:

```text
atlas mount github.com/sergio-sisternes-epam/okf-atlas
```

Compile/query root: `.../okf-atlas/atlas` (OKF root is `atlas/SCHEMA.json`, not the git root).

Do not use `okf-wiki` for new process memory. Do not add `references/atlas`, `references/wiki`, or any knowledge store to this package.

## Support

Source, issues, changelog, and release history:
https://github.com/sergio-sisternes-epam/okf

See `CONTRIBUTING.md` for validation and release handoff.
