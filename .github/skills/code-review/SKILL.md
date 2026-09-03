---
name: code-review
description: >-
  Use this skill when GitHub Copilot code review runs, when reviewing a
  pull request, or when asked to review code in this atlas repository.
  Apply even if the user only says "review this PR" or "@copilot review".
  Run an advisory multi-lens panel for atlas (SCHEMA/compile contract,
  Python CLI, skill/path discipline, security/gitops). Leave inline
  comments on findings and one summary table (Blocker / Recommended /
  Nits) with per-lens expandable detail. Do not implement, merge, or
  approve.
license: Apache-2.0
---

# Atlas code review (advisory panel)

You are the **orchestrator**. Specialists do not write to the PR. You are the sole public writer.

## Hard rules

- **Orchestrator writes; specialists do not.** Lenses return structured findings only.
- **Inline + one summary:** for each finding with a diff line, leave an inline comment on that line. Then post **exactly one** summary comment (table + per-lens `<details>`). No extra per-lens top-level comments.
- **Advisory only:** do not approve, request-changes as a merge gate, merge, or apply APPROVE/REJECT labels.
- **Do not implement** the PR under review.
- **Lazy load:** read a lens file only after the roster says that lens runs. Do not paste lens bodies into this file.
- **Review lens** ≠ atlas compile `--path`/`--type` **focus lens**. Do not mix those words.

## Procedure

1. Gather the change set read-only (diff, changed paths, PR body).
2. Load `references/roster.md`. Compute **always-on ∪ conditional − skip**. Cap: 4 specialists + synthesizer. Typical: 2–3.
3. Run each selected lens in **isolation**:
   - If child threads / sub-agents exist: spawn one thread per lens; each thread loads only its lens file + the diff.
   - If not (Copilot code review): evaluate lenses **sequentially** but do **not** show later lenses earlier findings. Each pass returns only the finding schema.
4. Completeness gate: every selected lens returned (or recorded skip/fail). Then load `references/finding-schema.md` and `references/synthesizer.md`.
5. Spawn or run the synthesizer with **findings only** (not lens bodies).
6. **Inline comments:** one per finding that cites a line in the new-side diff. Prefix with **Blocker** / **Recommended** / **Nit**. Skip inline if the line is not in the diff (summary only).
7. **Summary comment:** follow `references/synthesizer.md` (counts table + expandable panel per lens). Humans decide.

## Weights

`Blocker` | `Recommended` | `Nit`

Ship recommendation: `ship now` | `ship with follow-ups` | `needs discussion` | `needs rework`.
