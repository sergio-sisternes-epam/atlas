---
name: skill-agent-contract
---

# Review lens: skill-agent-contract

Run only when the roster includes this lens.

## Check

- Root `SKILL.md` stays a thin router. Path procedures live in `references/paths/<path>.md` and are loaded before execute.
- Progressive disclosure: do not inline every path module into the root skill.
- Nested skill calls use the multi-harness substrate contract (load the full target skill body; do not invent from memory).
- Frontmatter `description` names triggers and bounds (imperative, user intent).
- No harness-specific hard bounds in the skill body (Copilot/Claude-only syntax in the portable contract).
- `apm.yml` identity (name/version) stays consistent with `SKILL.md` when the **atlas package** changes — this Copilot skill is not an APM package.

## Do not

- Ask for a new APM package under `.github/skills/code-review/`.
- Re-check SCHEMA page-contract (atlas-contract).
