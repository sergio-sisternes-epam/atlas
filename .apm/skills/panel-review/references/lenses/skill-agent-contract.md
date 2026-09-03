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
- Root `apm.yml` identity (name/version) stays consistent with root `SKILL.md`; the nested `panel-review` skill keeps its own frontmatter name.

## Do not

- Ask for a nested APM package inside the generated Copilot skill.
- Re-check SCHEMA page-contract (atlas-contract).

## Receipt

Return JSON only against the supplied panelist schema. Set `lens_id` to
`skill-agent-contract`. The non-empty summary states the lens takeaway. Provide
one to three concrete coverage statements naming the dispatch, disclosure,
path, or APM contracts checked, even when `findings` is empty. Use
`status: failed` only when the rubric could not be reviewed, and explain the
limitation.
