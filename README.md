# atlas

Atlas is a durable OKF v0.2 knowledge substrate for agent process memory,
decisions, work hubs, and project knowledge graphs. It is distributed as a
root APM skill bundle; the `okf` package remains the format authority.

## What it provides

- Query, remember, work, landscape, and schema workflows selected by intent.
- A deterministic Python CLI for Atlas creation, validation, search, mounting,
  migration, promotion, and schema governance.
- Templates and reference procedures for durable OKF stores.
- Broad skill-runtime compatibility without harness-specific instructions.

## Prerequisites

- APM CLI 0.30.0 or newer.
- Python 3.10 or newer.
- The `sergio-sisternes-epam` APM marketplace, registered as:

  ```text
  apm marketplace add sergio-sisternes-epam/apm-marketplace --name sergio-sisternes-epam
  ```

- Access to the private `sergio-sisternes-epam/atlas` and
  `sergio-sisternes-epam/okf` repositories.
- Python dependencies from `scripts/requirements.txt`.

The optional `discuss` companion skill owns wrong-frame termination workflows.
Atlas probes for it only when that path is requested; it is not a manifest
dependency because `discuss` already depends on Atlas.

## Install

After the source owner publishes an immutable tag matching the `version` in
`apm.yml`:

```text
apm install sergio-sisternes-epam/atlas#vX.Y.Z
```

APM deploys the skill to the consumer's selected target. The package does not
pin one harness; it is validated against the shared Agent Skills target and
APM's stable multi-runtime target set.

Install the CLI's Python dependencies in the environment that runs Atlas:

```text
python3 -m pip install -r <atlas-skill>/scripts/requirements.txt
```

## Use

Invoke Atlas through the agent runtime for knowledge-store requests, or run the
deterministic CLI from the resolved skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py --help
python3 <atlas-skill>/scripts/atlas.py search "authentication decision" \
  --root <atlas-root> --json
```

The skill emits an activation card and loads exactly one procedure from
`references/paths/` before acting.

### Mount credentials

Atlas applies `ATLAS_PAT`, `GITHUB_TOKEN`, `GH_TOKEN`, and `GITHUB_APM_PAT`
only to `github.com` and GitHub Enterprise Cloud (`*.ghe.com`). For GitHub
Enterprise Server automation, set `GH_HOST` to the exact server hostname and
use `GH_ENTERPRISE_TOKEN` or `GITHUB_ENTERPRISE_TOKEN`; `ATLAS_PAT` and
`GITHUB_APM_PAT` are also accepted when paired with that exact `GH_HOST`.
Credentials stored by `gh auth login --hostname <host>` remain supported.

For any unmatched host, Atlas attempts anonymous HTTPS with credential helpers
disabled. It never forwards generic GitHub environment tokens to that host.
Use `--ssh` or authenticate the exact host with `gh` when anonymous access is
not sufficient.

## Process-memory store

Process memory is **not** authored in this package. The canonical store is:

https://github.com/sergio-sisternes-epam/atlas-atlas

Git root **is** the OKF root (`SCHEMA.json`). Load path `mount` (`references/paths/mount.md`), then:

```text
python3 <atlas-skill>/scripts/atlas.py mount \
  github.com/sergio-sisternes-epam/atlas-atlas \
  --ref main
```

Default mount = git submodule at `.atlas/github.com/sergio-sisternes-epam/atlas-atlas` (compile/query root)

## Contents

| Resource | Purpose |
| --- | --- |
| `CHANGELOG.md` | Unreleased user-visible changes |
| `SKILL.md` | Runtime router, invariants, and CLI surface |
| `references/paths/` | Query, remember, work, landscape, and schema procedures |
| `references/templates/` | OKF content templates |
| `scripts/atlas.py` | Atlas CLI entry point |
| `scripts/atlas_cli/` | CLI implementation |
| `fixtures/` | Validation fixtures used by the package test suite |

## Support and maintenance

Source, issues, and release history:
https://github.com/sergio-sisternes-epam/atlas

See `CONTRIBUTING.md` for validation, CI credentials, and the release handoff.

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

See `references/paths/mount.md` for the mount protocol.
