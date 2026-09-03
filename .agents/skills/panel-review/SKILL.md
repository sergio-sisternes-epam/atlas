---
name: panel-review
description: >-
  Use this skill when asked to review a pull request, run a panel review,
  or perform a multi-lens code review in this atlas repository. Apply even
  if the user only says "review this PR" or "@copilot review". Run an
  advisory panel for atlas (SCHEMA/compile contract, Python CLI, skill/path
  discipline, security/gitops). Leave inline comments on findings and one
  summary table (Blocker / Recommended / Nits) with per-lens expandable
  detail. Do not implement, merge, or set a formal review state.
license: Apache-2.0
---

# Atlas panel review

You are the **orchestrator**. Specialists do not write to the PR. You are the sole public writer.

## Hard rules

- **Orchestrator writes; specialists do not.** Lenses return structured findings only.
- **Inline + one summary:** for each finding with a diff line, leave an inline comment on that line. Then post **exactly one** summary comment (table + per-lens `<details>`). No extra per-lens top-level comments.
- **Advisory only:** leave formal review-state decisions and merging to humans; never apply merge-decision labels.
- **Do not implement** the PR under review.
- **Lazy load:** read a lens file only after the roster says that lens runs. Do not paste lens bodies into this file.
- **Review lens** ≠ atlas compile `--path`/`--type` **focus lens**. Do not mix those words.

## Procedure

1. Gather the change set read-only (diff, changed paths, PR body).
2. Load `references/roster.md`. Compute **always-on ∪ conditional − skip**. Cap: 4 specialists + synthesizer. Typical: 2–3.
3. Run each selected lens in **isolation**:
   - If child threads / sub-agents exist: spawn one thread per lens; each thread loads only its lens file + the diff.
   - If isolated child threads are unavailable: stop and report that a true panel cannot run. Do not simulate multiple lenses in one context.
4. Completeness gate: every selected lens returned (or recorded skip/fail). Then load `references/finding-schema.md` and `references/synthesizer.md`.
5. Spawn or run the synthesizer with **findings only** (not lens bodies).
6. **Inline comments:** one per finding that cites a line in the new-side diff. Prefix with **Blocker** / **Recommended** / **Nit**. Skip inline if the line is not in the diff (summary only).
7. **Summary comment:** follow `references/synthesizer.md` (counts table + expandable panel per lens). Humans decide.

## Weights

`Blocker` | `Recommended` | `Nit`

Ship recommendation: `ship now` | `ship with follow-ups` | `needs discussion` | `needs rework`.
