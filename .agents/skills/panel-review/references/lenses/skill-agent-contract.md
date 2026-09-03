---
name: skill-agent-contract
---

# Review lens: skill-agent-contract

Run only when the roster includes this lens.

## Check

- When the root Atlas `SKILL.md` changes, it stays a thin router. Atlas path
  procedures live in `references/paths/<path>.md` and are loaded before execute.
  Nested skills use their own local references/assets and do not need Atlas path
  procedure modules.
- When `code-review` is the broad review entrypoint, it loads the sibling
  `panel-review` skill through a valid relative link and fails closed when the
  panel cannot execute. It does not copy panel orchestration or output rules.
- Progressive disclosure: do not inline every path module into the root skill.
- Nested skill calls use the multi-harness substrate contract (load the full target skill body; do not invent from memory).
- Frontmatter `description` names triggers and bounds (imperative, user intent).
- No harness-specific hard bounds in the skill body (Copilot/Claude-only syntax in the portable contract).
- Root `apm.yml` keeps package identity `atlas`; nested review skills keep their
  own directory-matching names. These names serve different scopes and must not
  be forced to match.
- Skill frontmatter follows the supported skill contract (`name` and
  `description`; existing package metadata may remain). Do not request a
  `version` field in nested `SKILL.md`.
- Contributor panel evals stay outside the deployed skill bundle and remain
  aligned with the runtime receipt schemas and recommendation template.

## Do not

- Ask for a nested APM package inside the generated Copilot skill.
- Re-check SCHEMA page-contract (atlas-contract).
- Infer that an unchanged manifest field or existing file is absent because a
  partial diff does not show it. Inspect the current changed file first.

## Receipt

Return JSON only against the supplied panelist schema. Set `lens_id` to
`skill-agent-contract`. The non-empty summary states the lens takeaway. Provide
one to three concrete coverage statements naming the dispatch, disclosure,
path, or APM contracts checked, even when `findings` is empty. Use
`status: failed` only when the rubric could not be reviewed, and explain the
limitation.
