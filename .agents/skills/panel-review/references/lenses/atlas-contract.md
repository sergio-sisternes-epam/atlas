---
name: atlas-contract
---

# Review lens: atlas-contract

Always-on. Knowledge-store integrity for this package.

## Check

- `SCHEMA.json` remains the compile authority. Do not invent parallel schema.
- `staging/` never answers. Compile must hard-fail if staging is non-empty.
- Pages with `work_id` include `relates_to` the work hub with `kind: implements`.
- Protostars include `kind: derived_from` to origin. No `residuals/` buckets.
- Path protocol vs CLI tool stay distinct (`path: query` vs `atlas search`; compile gate vs search inventory).
- Skills with `activation_card: on` keep Enter card + path-module load.
- Frontmatter required keys for the page type still hold.

## Do not

- Re-review Python call graphs (python-cli) or auth token handling (security-gitops).
- Treat compile `--path`/`--type` as this panel's "lenses".

## Receipt

Return JSON only against the supplied panelist schema. Set `lens_id` to
`atlas-contract`. The non-empty summary states the lens takeaway. Provide one
to three concrete coverage statements naming checks actually performed, even
when `findings` is empty. Use `status: failed` only when the rubric could not be
reviewed, and explain the limitation.
