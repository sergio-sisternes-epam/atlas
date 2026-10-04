---
name: atlas/paths/memory-migrate
path_id: memory-migrate
description: Use this path when a store still treats documents as the core record, or when compile is only reporting legacy document and missing gist noise, and you need to migrate toward Atlas memory. Triggers include document-era store, old scheme, legacy type document, missing gist, memory rung, opt in from info to warn. Do not use it to relocate a store (path migrate), to install the recall index (path configure), to edit SCHEMA.json by hand, or to run a Discuss checkpoint.
---

# Path: memory-migrate

## When

A store still treats `document` as the core record, or `atlas compile` is
mostly reporting `legacy_document` and `missing_gist` noise, and the operator
wants to move that store toward the memory layers (`frame`, `gist`, `memory`).

Not for relocating a store (use path **migrate**). Not for installing the
recall index (use path **configure**). Not for hand-editing `SCHEMA.json`.
Not for a Discuss checkpoint or constellation path — none exists in Atlas.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: memory-migrate
path_module: references/paths/memory-migrate.md
intent: assess or migrate a document-era store
root: <resolved SCHEMA root>
rung: info | warn | error
operation: assess | inventory | apply
```

Then **read this file**. Missing card or unloaded module means Enter is
incomplete.

## Procedure

### assess

Run:

```bash
python3 <atlas-skill>/scripts/atlas.py compile --root <root> --json --dry-run
```

`--dry-run` still reports every finding (including `legacy_document`,
`missing_gist`, `gist_parent`, `frame_members`), but never writes
`mesh.json` and never publishes the recall index — an unfocused compile
would otherwise do both. The compile JSON includes a `memory_rung` field:
the effective rung (`info`, `warn`, or `error`) resolved the same way as
`SCHEMA.memory.rung`. Whether an absent, missing, or blank `rung` is
benign depends on the schema:

- **SCHEMA 1.0** (no `validate_store_v2`): an absent `memory` key, a
  missing or null `rung`, or a blank/whitespace string `rung` all mean
  effective rung `info`, with no `memory_rung` critical finding. That
  rung shape contributes no failure of its own, but it does **not**
  guarantee exit 0 — other actionable warnings (for example a missing
  `index.md` / `index_md_present`) still make assess exit 1, and other
  critical findings still make it exit 2. The overall compile exit
  policy still applies.
- **SCHEMA 2.0** (`validate_store_v2`, `rung` typed as a string enum
  `info` | `warn` | `error`): the default `info` rung is only reached by
  *omitting* the `rung` key, or by omitting `memory` entirely. Even then,
  this does not by itself guarantee exit 0 if other warnings or criticals
  are present. A **present** `rung` that is null or a blank/whitespace
  string fails the schema's own validation (`schema_v2`, not just
  `memory_rung`) and exits 2. Do not tell a SCHEMA 2.0 operator that a
  present null or blank rung is benign; tell them to remove the key
  instead.

A malformed `rung` — a non-string value such as `0`, `false`, `[]`, or
`{}`, or a string that is not `info`, `warn`, or `error` — does **not**
behave like an absent/omitted rung on either schema. `_memory_rung` emits
a critical finding (id `memory_rung`), so assess fails closed and exits 2;
on SCHEMA 2.0 this also fails `schema_v2`. The compile JSON `memory_rung`
field still reports the effective ladder `info` for that run, but that
field is not the exit code — do not read a malformed configuration as
benign because the field says `info`. Report the memory rung in effect
(read from `memory_rung`) and the finding ids present. Write nothing. Do
not edit `SCHEMA.json`.

### inventory

Same facts as assess, plus a short judgement of which named batch of pages
could reasonably move toward `memory`/`gist`/`frame` next. Write nothing. Do
not create frames automatically — mining the whole store for repeated
patterns across gists is out of scope for this path.

### apply

Only when the operator asks and names the batch. Refuse an unscoped or
unattested "migrate everything" request. For that named batch only:

1. Use path **remember** to retype, add a gist, or add a frame as named by
   the operator. Remember's index-only exception applies here: a first
   compile that exits 1 solely for `index_md_present` / missing `index.md`
   may proceed to create or update that folder's hot list, then the second
   compile must exit 0 before the page counts as stored.
2. **Batch-scoped validation** — after each remember (or after the batch),
   compile focused on the named batch path(s), not the whole store:
   ```bash
   python3 <atlas-skill>/scripts/atlas.py compile --root <root> --path <batch-prefix> [--type <type>]
   ```
   Focused `--path` / `--type` omit out-of-batch pages, so legacy
   `document` / `missing_gist` findings elsewhere do not block an in-batch
   finish once the store is at `warn` or `error`. Folder-level `frame_members`
   findings follow the same descendant-only path prefix: focus the folder
   (or an ancestor), not an individual file, to include them. Type focus
   includes a folder finding when a direct concept page has that type;
   `--type gist` therefore includes missing-frame findings, while
   `--type frame` includes multiple-frame findings but not folders with
   no frame. Both filters apply when combined. Folder findings have no
   page body for inline ignores and remain on the configured memory rung.
   A red focused compile
   stops the batch — fix before moving to the next page. There is no
   unattended bulk rewrite and **no** whole-store rewrite authorised here.
3. **Optional rung-hold** — if the operator explicitly attests a temporary
   hold (keep `memory.rung` at `warn`/`error` while finishing this named
   batch only), apply may continue under that rung for in-batch pages
   validated with the focused compile above. The hold does not waive
   focused-compile failures, does not authorise rewriting pages outside
   the batch, and does not change `SCHEMA.json` (rung changes still go
   through path **schema** when the operator asks).

### Rung changes

Changing `memory.rung` goes through path **schema**
(`atlas schema memory-rung --set info|warn|error`), and only when the
operator asked to opt the rung in from `info` toward `warn` or `error`.
This path does not write `SCHEMA.json` itself.

### Out of scope

Do not load Discuss. Do not add a checkpoint or constellation path — Discuss
still owns `constellation`. Do not use path **migrate** (that path relocates
a store, it does not change memory layers).

## Exit receipt

```text
skill: atlas
path: memory-migrate
root: …
compile: exit N
operation: assess | inventory | apply
batch: <named batch, apply only>
```

## Non-goals

- Relocating a store (path **migrate**)
- Installing or configuring recall (path **configure**)
- Hand-editing `SCHEMA.json`
- Bulk, unattended rewriting of document pages
