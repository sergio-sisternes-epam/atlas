---
name: python-cli
---

# Review lens: python-cli

Run only when the roster includes this lens.

## Check

- CLI fail-closed: unknown options and contract misses must not exit 0.
- `--path` / filesystem args stay inside the atlas root (no `../`, no absolute escape).
- Focused compile (`--type`, `--path`) still emits issues; it must not swallow the gate.
- New behaviour covered by `references/scenarios/*-adversarial-vN.yaml` or an explicit deferral.
- Fixtures under `fixtures/` stay consistent with SCHEMA and CLI claims.
- Keep Click/argparse surfaces documented in `SKILL.md` CLI table when adding verbs.

## Do not

- Nitpick formatting that linters own.
- Duplicate security-gitops (secrets, auth store) unless the bug is CLI exit-code / path-escape.

## Receipt

Return JSON only against the supplied panelist schema. Set `lens_id` to
`python-cli`. The non-empty summary states the lens takeaway. Provide one to
three concrete coverage statements such as the CLI paths, fail-closed behavior,
or fixtures checked, even when `findings` is empty. Use `status: failed` only
when the rubric could not be reviewed, and explain the limitation.
