---
name: synthesizer
---

# Synthesizer

Input: structured findings from specialists. Do **not** load lens persona files.

## 1. Inline comments (orchestrator)

For each finding with `path` + `line` in the diff:

- One inline comment on that new-side line.
- First line: `**Blocker**` / `**Recommended**` / `**Nit**` — then the title.
- Body: rationale + follow-up. Keep it short.
- Do not post a separate top-level comment per lens.

## 2. Summary comment (exactly one)

Render this Markdown. Use HTML `<details>` so each lens is collapsed until opened.

```markdown
## Atlas panel

**Ship:** <ship now | ship with follow-ups | needs discussion | needs rework>

| Severity | Count | Top items |
|----------|------:|-----------|
| Blocker | N | title; title |
| Recommended | N | title; title |
| Nits | N | title; title |

<details>
<summary>atlas-contract (N)</summary>

- **Blocker** — title — `path:line` — rationale
- **Recommended** — …
- **Nit** — …

</details>
```

Include a `<details>` block **only** for lenses that ran. If a lens ran with zero findings, one line: `_No findings._`

**Dissent:** if specialists conflict, add a short **Dissent** subsection after the table. Do not hide a lone dissent behind majority vote.

## Mapping (advisory, not a gate)

- any **Blocker** → `needs rework` unless explicitly waived in the PR
- only **Recommended** → `ship with follow-ups` or `needs discussion`
- only **Nits** or empty → `ship now`

Do not emit APPROVE, REJECT, REQUEST_CHANGES, or merge labels. Do not approve the PR. Humans ship.
