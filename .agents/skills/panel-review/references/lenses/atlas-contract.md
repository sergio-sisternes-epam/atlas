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
