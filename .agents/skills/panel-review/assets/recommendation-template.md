## Atlas panel: {{ship_recommendation.stance}}

**{{headline}}**

{{synthesis}}

{{dissent_section_if_present}}

| Lens | Blocker | Recommended | Nits | Takeaway |
|---|---:|---:|---:|---|
{{one_nonempty_row_per_selected_lens}}

{{top_items_section_if_nonempty}}

### Advisory recommendation

{{ship_recommendation.rationale}}

{{one_details_block_per_selected_lens}}

Per-lens block:

<details>
<summary>{{lens_id}} - {{summary}}</summary>

**Coverage**

- {{concrete_check_performed}}

{{limitations_section_if_nonempty}}

**Findings**

{{full_findings_or_clean_sentence_referring_to_coverage}}

</details>

Rendering rules:

- Preserve the section order above.
- Omit the dissent, top-items, and limitations sections when they are empty.
- Render every selected lens with a non-empty takeaway and coverage list.
- Use zeroes in count cells; never leave a table cell blank.
- For a clean lens, write "No findings after the checks above." under Findings.
- Include at most three top items.
- Keep this as the only top-level panel summary comment.
