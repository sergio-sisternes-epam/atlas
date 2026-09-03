---
name: panel-review
description: >-
  Use this skill when asked to review a pull request, run a panel review,
  or perform a multi-lens code review in this Atlas repository. Apply even
  when the user only asks to review the PR. Run a cost-aware advisory panel
  over the relevant Atlas contract, Python CLI, skill/agent, and
  security/gitops surfaces. Publish inline findings plus one evidence-backed
  summary. Do not implement, merge, or set formal review state.
license: Apache-2.0
---

# Atlas panel review

You are the orchestrator and sole public writer. Panelists and the synthesizer
never write to the PR.

## Hard rules

- **Single writer:** panelists and synthesizer return receipts only.
- **Inline then one summary:** publish every diff-backed finding as an inline
  comment, then exactly one Blocker/Recommended/Nits summary with expandable
  detail for every selected lens. Never post per-lens top-level comments.
- **Advisory only:** humans own formal review state and merging. Never apply
  merge-decision labels or implement the reviewed change.
- **Lazy load:** load only selected lens files. Do not send one panelist another
  lens body.
- A review lens is not an Atlas compile `--path`/`--type` focus lens.

## Procedure

1. Gather the PR title, body, changed paths, and unified diff read-only.
2. Load `references/roster.md` and classify in the parent from paths and PR
   intent. Record selected lens ids and a reason for every skipped lens. This
   is not a model call. Select the minimum useful roster: normally one or two,
   never more than four.
3. Load `assets/panelist-receipt.schema.json`. For each selected lens, start one
   isolated reviewer-class, low-effort child. Give it this compact brief, its
   lens file, the schema, and PR context. Permit read-only access to the current
   versions of changed files when omitted diff context must be resolved:

   ```text
   ROLE: <lens-id> reviewer. RESPOND JSON ONLY.
   CHECK: assigned rubric only. NO cross-lens findings. NO writes.
   FACTS: do not infer absence from a partial diff; inspect the current changed
   file before claiming a required field, file, or test is missing.
   WEIGHTS: Blocker=demonstrated correctness/security/contract failure;
   Recommended=substantive follow-up; Nit=optional polish.
   RETURN: status, non-empty summary, coverage[1..3], findings[], limitations[].
   ```

   If isolated children are unavailable, stop and explain that a true panel
   cannot run. Do not simulate several lenses in one context.
4. Validate each receipt before fan-in: parse JSON; apply the panelist schema;
   require the assigned `lens_id`;    require useful, concrete summary and coverage; fact-check each finding's
   evidence against the current file or diff; reject findings based on omitted
   diff context or outside the assigned lens; and verify any `path` plus `line`
   is a new-side diff location.
   Require `path` plus `line` when a changed line can carry the finding; omit
   them only for repository-level findings with no eligible changed line.
   Retry only a malformed slot once, providing its validation errors. If the
   retry fails, create a schema-valid `status: failed` receipt whose summary,
   coverage, and limitations explain that no review evidence was produced.
   Do not rerun valid slots.
5. After every selected slot has a valid receipt, load
   `assets/synthesizer-receipt.schema.json`. Start one reviewer-class,
   low-effort synthesizer with validated receipts only, never lens bodies:

   ```text
   ROLE: dissent-weighted panel synthesizer. RESPOND JSON ONLY.
   INPUT: validated receipts only. NO new findings. Preserve lone dissent.
   RETURN: headline, synthesis, optional dissent, top_items<=3,
   ship_recommendation. Explain clean results from summaries and coverage.
   ```

   Validate its receipt against the schema and source receipts: every top item
   must match an input finding, text must be non-empty, and bounds must hold.
   Retry malformed synthesis once. If it still fails, construct a valid
   `needs discussion` fallback that reports synthesis failure and retains no
   top items; never invent a technical finding.
6. Load `assets/recommendation-template.md`. Render normal human-readable
   Markdown. Omit optional sections rather than leaving empty placeholders.
7. Using the deterministic GitHub publication tools, first publish one inline
   comment for each finding with a verified new-side diff location. Prefix it
   with **Blocker**, **Recommended**, or **Nit**, then include rationale and
   follow-up. Findings without an inline-eligible location remain in the
   summary only.
8. Publish exactly one rendered summary. Include one row and one expandable
   block per selected lens. A clean lens must show its concrete coverage, not
   an empty accordion or only "No findings."

## Weights

`Blocker` | `Recommended` | `Nit`

Ship recommendation: `ship now` | `ship with follow-ups` | `needs discussion` | `needs rework`.
