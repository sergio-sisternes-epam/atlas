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
