---
name: security-gitops
---

# Review lens: security-gitops

Run only when the roster includes this lens. Higher stakes.

## Check

- No secrets, tokens, or credentials in git, fixtures, staging, logs, or skill text.
- Auth store and mount/gitops changes stay fail-closed; do not log tokens.
- Path arguments cannot escape the atlas root.
- `staging/` must not become an answerable corpus (also a compile rule; flag leakage here).
- Submodule/mount operations do not write credentials into the tree.

## Do not

- Generic web-OWASP theatre unrelated to this CLI.
- Style nits.

## Receipt

Return JSON only against the supplied panelist schema. Set `lens_id` to
`security-gitops`. The non-empty summary states the security takeaway. Provide
one to three concrete coverage statements naming the trust boundary, credential
flow, or fail-closed behavior checked, even when `findings` is empty. Use full
sentences where compression could make a warning ambiguous. Use
`status: failed` only when the rubric could not be reviewed, and explain the
limitation.
