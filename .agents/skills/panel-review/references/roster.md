---
name: review-lens roster
---

# Roster

These are **review lenses**. Not atlas compile `--path`/`--type` focus lenses.

| id | File | Select when |
|----|------|-------------|
| atlas-contract | `references/lenses/atlas-contract.md` | Always. |
| python-cli | `references/lenses/python-cli.md` | Atlas runtime or CLI behavior changes: executable Python under `scripts/`, runtime fixtures, or a scenario that exercises CLI/compile behavior. |
| skill-agent-contract | `references/lenses/skill-agent-contract.md` | Skill, agent, APM, instruction, path procedure, recipe, or template changes. |
| security-gitops | `references/lenses/security-gitops.md` | Behavioral changes to auth, credentials, git/mount, submodules, staging answerability, or filesystem boundaries. |

Select from changed paths plus the concise PR intent. A mention of a security
term in review documentation is not a behavioral change and does not select the
security lens. A scenario selects `python-cli` only when it exercises CLI or
compile behavior. Contributor-only Python, renderer/eval tooling, documentation
snippets, and review fixtures do not select `python-cli`.

Load only selected lens files. Record why each other lens was skipped. Do not
make a separate model call for routing.

The always-on count is one. A docs-only PR normally runs only
`atlas-contract`; a focused code or skill PR normally runs two lenses. Use all
four only for a cross-cutting, high-risk change. The hard maximum is four
panelists plus one synthesizer.
