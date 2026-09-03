---
name: code-review
description: >-
  Use this skill whenever GitHub Copilot code review runs or the user asks to
  review a pull request or its code changes in this Atlas repository. Treat it
  as the mandatory review entrypoint: load the sibling panel-review skill and
  execute its procedure end-to-end. Do not substitute a generic single-pass
  review, implement the reviewed change, merge, or set formal review state.
license: Apache-2.0
---

# Atlas code review

This skill is the review discovery adapter. The sibling panel owns review
analysis, validation, synthesis, and publication.

## Mandatory panel step

1. Confirm that the target is a pull request or reviewable change set and gather
   its repository identity read-only.
2. LOAD [panel-review](../../../.apm/skills/panel-review/SKILL.md).
3. Execute the loaded panel procedure end-to-end. Its hard rules, roster,
   receipt schemas, validation gates, and publication order are authoritative.
4. If the sibling skill cannot be loaded, stop and report that the panel is
   unavailable. Runtime execution fallback remains owned by `panel-review`;
   do not substitute adapter-owned analysis.

## Ownership boundary

- `code-review` owns broad review discovery and the mandatory delegation step.
- `panel-review` is the sole review orchestrator and public writer.
- Do not duplicate lens selection, finding weights, receipt validation,
  synthesis, or summary formatting in this skill.
- Keep the review advisory. Humans own formal review state and merging.
- Do not implement changes in the pull request under review.
