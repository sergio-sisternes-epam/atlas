---
name: okf-authority
description: Format authority for Open Knowledge Format. Use for questions about OKF rules, compliance, frontmatter requirements, or validation of any OKF-conformant bundle.
---

# OKF Authority

Pure format authority for Open Knowledge Format (OKF) **v0.2**.

## What OKF is

OKF is an open, human- and agent-friendly format for representing knowledge as a directory of Markdown files with YAML frontmatter. It is intentionally minimal: if you can `cat` a file and `git clone` a repo, you can use it.

This skill implements the pure format standard only. It knows nothing about live knowledge-store operations (ingest, query, lint of a session store). Those belong to Atlas (`atlas mount github.com/sergio-sisternes-epam/okf-atlas`; compile/query root `.../okf-atlas/atlas`).

## Normative rules (hard)

1. Every non-reserved `.md` file **must** contain parseable YAML frontmatter.
2. Every frontmatter block **must** contain a non-empty `type` field.
3. Reserved filenames (at any level): `index.md`, `log.md`. These must not be used as concept documents.
4. Directory structure is independent of domain — producers organise as they wish.
5. Consumers **must not** reject a bundle for: missing optional fields, unknown `type` values, unknown additional frontmatter keys, or broken cross-links.
6. Prefer update-over-create. Never strip unknown frontmatter keys on import/export round-trips.
7. Links should be resolvable inside the target environment after import/export.

## Required frontmatter

```yaml
---
type: <string>          # REQUIRED — free-form, not centrally registered
---
```

`type` is the **only** always-required field. Type values are not registered centrally; consumers must tolerate unknown types.

## Recommended frontmatter (v0.1 carried forward)

| Field | Purpose |
|-------|---------|
| `title` | Human-readable display name |
| `description` | One-sentence summary |
| `resource` | Canonical URI for the underlying asset (omit for abstract concepts) |
| `tags` | YAML list for cross-cutting categorisation |

## OKF v0.2 provenance, trust & lifecycle families (optional but first-class)

These families are additive in v0.2. Their absence is valid; when present they should be treated as queryable signals.

### Provenance — `sources`

```yaml
sources:
  - uri: https://example.com/doc
    author: human:alice
    usage_count: 3
    last_modified: 2026-06-01T12:00:00Z
```

Replaces the older body-level `# Citations` list. Consumers MAY still parse a legacy citations list for v0.1 documents.

### Generation & verification

```yaml
generated:
  by: agent:my-agent
  at: 2026-08-23T12:00:00Z

verified:
  - by: human:bob
    at: 2026-08-23T14:00:00Z
```

- `generated` supersedes the simple `timestamp` field of v0.1. Consumers MAY fall back to a legacy `timestamp` when `generated` is absent.
- Trust tier is derived:
  - no `verified` → `unverified`
  - only non-`human:` actors → `machine-confirmed`
  - any `human:<id>` actor → `human-reviewed`

### Lifecycle / freshness

```yaml
status: draft | stable | deprecated
stale_after: 2026-12-31T00:00:00Z
```

### Attested Computation (new concept type in v0.2)

When `type: Attested Computation` (or equivalent), additional keys may appear (`runtime`, `parameters`, `computation`, `executor`, `attester`, etc.). See the public OKF v0.2 specification for the full contract.

## Reserved files

| File | Purpose |
|------|---------|
| `index.md` | Directory listing for progressive disclosure. Normally no frontmatter; the bundle-root index MAY carry `okf_version: "0.2"`. |
| `log.md` | Chronological change history, newest first. |

Both may appear at any level of the hierarchy.

## Conformance checklist

A bundle is conformant when:

- [ ] Every non-reserved `.md` has parseable YAML frontmatter
- [ ] Every frontmatter has a non-empty `type`
- [ ] Reserved files follow their structural expectations when present
- [ ] No concept is named `index.md` or `log.md`
- [ ] Unknown types and unknown frontmatter keys are tolerated by consumers

## What this module does **not** do

- Live knowledge operations (ingest, query, expand, lint of a session store).
- Concrete folder ontologies or operational process (those belong to the operational skill built on top of OKF).
- Enforcing the optional v0.2 provenance/trust/lifecycle families as required fields.

## When to hand off

- Live knowledge-store / Atlas work → `atlas mount github.com/sergio-sisternes-epam/okf-atlas` (compile/query root `.../okf-atlas/atlas`). Do not use `okf-wiki` for new process memory.
- Pure format / compliance / validation questions → stay here
