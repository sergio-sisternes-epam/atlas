---
name: finding-schema
---

# Finding schema

Each specialist returns a list of objects. No free-form essay as the only output.

```text
lens_id: atlas-contract | python-cli | skill-agent-contract | security-gitops
title: short noun phrase
rationale: why this matters in this repo
weight: Blocker | Recommended | Nit
path: repo-relative path
line: new-file line number (omit if not in the diff)
follow_up: suggested fix or tracked follow-up
```

Empty list is valid (lens ran, nothing to say). Do not invent findings to look busy.

**Inline eligibility:** set `line` only when that line appears in the PR diff (new side). Otherwise omit `line` and keep the finding in the summary only.
