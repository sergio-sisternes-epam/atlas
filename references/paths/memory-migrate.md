---
name: atlas/paths/memory-migrate
path_id: memory-migrate
description: Use this path when a store still treats documents as the core record, or when compile is only reporting legacy document and missing gist noise, and you need to migrate toward Atlas memory. Triggers include document-era store, old scheme, legacy type document, missing gist, memory rung, opt in from info to warn. Do not use it to relocate a store (path migrate), to install the recall index (path configure), to edit SCHEMA.json by hand, or to run a Discuss checkpoint.
---

# Path: memory-migrate

## When

A store still treats `document` as the core record, or `atlas compile` is
mostly reporting `legacy_document` and `missing_gist` noise, and the operator
wants to move that store toward the memory layers (`page`, `gist`, `frame`).

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
python3 <atlas-skill>/scripts/atlas.py compile --root <root> --json
```

Report the memory rung in effect and the finding ids present: `legacy_document`,
`missing_gist`, `gist_parent`, `frame_members`. Write nothing. Do not edit
`SCHEMA.json`.

### inventory

Same facts as assess, plus a short judgement of which named batch of pages
could reasonably move toward `page`/`gist`/`frame` next. Write nothing. Do
not create frames automatically — mining the whole store for repeated
patterns across gists is out of scope for this path.

### apply

Only when the operator asks and names the batch. Refuse an unscoped or
unattested "migrate everything" request. For that named batch only:

1. Use path **remember** to retype, add a gist, or add a frame as named by
   the operator.
2. Compile. A red compile stops the batch — fix before moving to the next
   page. There is no unattended bulk rewrite.

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
