---
name: review-lens roster
---

# Roster

These are **review lenses**. Not atlas compile `--path`/`--type` focus lenses.

| id | File | When | Skip |
|----|------|------|------|
| atlas-contract | `references/lenses/atlas-contract.md` | **always** | never |
| python-cli | `references/lenses/python-cli.md` | any changed path under `scripts/`, `*.py`, `fixtures/`, `references/scenarios/` | docs-only / SKILL-only / recipes-templates-only diffs (no Python, no fixtures, no scenarios) |
| skill-agent-contract | `references/lenses/skill-agent-contract.md` | `SKILL.md`, `references/paths/`, `references/recipes/`, `references/templates/`, `apm.yml` | pure Python internals with none of those files |
| security-gitops | `references/lenses/security-gitops.md` | `auth*`, `gitops`, `mount`, credentials, `staging`, `--path` / path-escape | otherwise |
| synthesizer | `references/synthesizer.md` | after specialists return | n/a |

Load **only** the files for lenses that run. Do not preload skipped lenses.

Always-on count is 1 (`atlas-contract`). Worst case is 4 specialists + synthesizer.
