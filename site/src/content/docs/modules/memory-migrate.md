---
title: memory-migrate
description: Assess a document-era Atlas store and, batch by named batch, move it toward the memory layers.
sidebar:
  order: 4
source:
  - references/paths/memory-migrate.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/memory-migrate.md: c577afd8c4363575664d567e310b3a8de3ef9067
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `memory-migrate` module moves an older store toward the Atlas memory layers.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
A *document-era* store still treats the legacy `document` type as its core record.
The *memory layers* are `memory` pages, *gists* (short pages derived from memory pages in the same folder) and a top page that lists the gists.
That top page is a `schema` on the current `CONTRACT.json` shape and a `frame` on shipped `SCHEMA.json` stores.
The module has three operations: `assess`, `inventory` and `apply`.
`assess` and `inventory` write nothing.

## When

Use `memory-migrate` when a store still treats `document` as the core record.
Also use it when the `compile` command reports mostly `legacy_document` and `missing_gist` findings.
*Compile* checks the store's contract shape, required frontmatter and required links.

A leftover `missing_gist` finding is not a completeness failure.
This module does not create gists. The agent never invents gist text or a title-only stub to clear that finding.

## What it does

### assess

The agent runs a dry-run compile:

```text
python3 <atlas-skill>/scripts/atlas.py compile --root <root> --json --dry-run
```

`--dry-run` reports every finding but never writes `mesh.json` and never publishes the recall index.
The JSON has a `memory_rung` field. The *memory rung* (`info`, `warn` or `error`) sets how strictly compile treats memory-layer findings.
The agent reports the rung in effect and the finding ids. It writes nothing and does not edit `SCHEMA.json`.

Some rules about the rung:

- On SCHEMA 1.0, a missing `memory` key or a missing, null or blank `rung` means `info`. That adds no failure of its own.
- On SCHEMA 2.0, `info` is reached only by omitting the `rung` key or the whole `memory` object. A present `rung` that is null or blank fails schema validation and exits 2. The agent tells you to remove the key.
- A malformed `rung` (not a string, or not `info`, `warn` or `error`) is a critical finding on both versions. Assess exits 2, even though the `memory_rung` field still shows `info`.
- A benign rung does not guarantee exit 0. Other warnings still give exit 1, and other critical findings still give exit 2.

### inventory

The agent reports the same facts as `assess`.
It adds a short judgement of which **named batch** of pages could move toward `memory`, `gist` and `schema` next.
It writes nothing and creates no files.
On shipped `SCHEMA.json` stores, the plan keeps the existing `frame_members` ladder.
On the current `CONTRACT.json` shape, the plan gives each set of gists an owning schema, cued from the folder `index.md`. Several schemas are fine when subjects differ.

### apply

`apply` runs only when you ask and name the batch.
A *batch* is a named set of pages. The agent validates it by its path prefix.
The agent refuses an unscoped or unattested "migrate everything" request.
For the named batch only:

1. The agent uses [`remember`](/atlas/modules/remember/) to retype a page, add a gist or add a schema, as you name.
   On the current shape, at least one same-folder schema must cover every gist.
   If the live subject changes, the agent adds another `<name>.schema.md`, links it to the prior schema and lists it in `index.md`. It does not rewrite sibling schemas.
   `hub.md` stays in place as a *work hub*, not a memory page.
2. After each remember, or after the batch, the agent compiles only the batch:

   ```text
   python3 <atlas-skill>/scripts/atlas.py compile --root <root> --path <batch-prefix> [--type <type>]
   ```

   Focused `--path` and `--type` leave out pages outside the batch.
   So legacy findings elsewhere do not block the batch at `warn` or `error`.
   To include folder-level findings, focus the folder or an ancestor, not a single file.
   A red focused compile stops the batch. The agent fixes it before the next page.
3. You may attest a temporary *rung hold*. The store then stays at `warn` or `error` while the agent finishes this batch only.
   The hold does not waive focused-compile failures. It does not allow writes outside the batch. It does not change `SCHEMA.json`.

There is no unattended bulk rewrite and no whole-store rewrite.

### Rung changes

Only the [`schema`](/atlas/modules/schema/) module changes `memory.rung`, through the `schema memory-rung` command.
It does so only when you ask to move the rung up from `info` to `warn` or `error`.
`memory-migrate` never writes the contract file itself.

### Contract-file migration (CLI)

The `memory-migrate` CLI command is a separate tool.
It rewrites the store's root contract file and adds the required schema pages. It does not rewrite existing pages.

```text
python3 <atlas-skill>/scripts/atlas.py memory-migrate --root <root> --operation assess|inventory|apply [--batch <token>] --json
```

- `assess` and `inventory` write nothing. The JSON reports a `lineage` (`pre-beta`, `in-beta`, `empty-beta2-init` or `current`) and a `contract_file_eligible` flag.
- Here a batch is a token, not a set of pages. The only implemented token is `contract-file`. `apply` with no `--batch`, or with "migrate everything", refuses and writes nothing.
- On an eligible store, `apply --batch contract-file` renames `SCHEMA.json` to `CONTRACT.json`, stamps `atlas_release` `0.13.0-beta.7` and sets `memory.layers` to `["schema", "gist", "memory"]`.
- Eligible stores are a pre-beta contract (`SCHEMA.json` with no `memory` object and no `atlas_release`, or one older than `0.13.0-beta`) and an empty, unstamped full beta.2 init.
- For the empty beta.2 init only, `apply` also aligns templates and recommended types with a fresh `init`. It keeps store-specific settings and custom types and templates.
- In-beta stores refuse with `in_beta_not_legacy` and write nothing. These are stores stamped `0.13.0-beta` or `0.13.0-beta.2`, stores with frame-based `memory.layers`, and a full beta.2 init that already has memory-layer pages.
- A current store is a no-op. Unknown stamps fail closed.
- The batch adds a `schema.schema.md` page in each gist-bearing folder that has no schema, and cues it from the folder index. Other `frame`, `gist` and `memory` pages stay byte-for-byte, except an unsuffixed `frame.md` that the new schema replaces.
- If a frame description cannot round-trip, `apply` exits 2 with `frame_description_not_round_trippable`. It leaves `frame.md` and `SCHEMA.json` unchanged, writes no `CONTRACT.json` and writes operator steps into `staging/`.

Install, compile and schema upgrade never run `apply`. Migration stays your choice.

## How to ask for it

Ask the agent to assess or migrate a document-era store, for example "assess this store for memory migration".
For `apply`, name the batch, for example a folder.
To learn about the module without running it, ask `/atlas help memory-migrate` or "explain memory-migrate".

## Activation card

The agent first emits [`mount`](/atlas/modules/mount/) to set `root`. Then it renders this card as a fenced `text` block:

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

A missing card or an unloaded module means Enter is incomplete.
The exit receipt records `root`, the compile exit code, the `operation` and, for `apply`, the named `batch`.

## Boundaries

- `assess` and `inventory` write nothing.
- No unscoped or unattested "migrate everything", and no unattended bulk rewrite of document pages.
- No manual edits to `SCHEMA.json`. Rung changes go through the `schema` module.
- Not for relocating a store. Use [`migrate`](/atlas/modules/migrate/).
- Not for installing or configuring recall. Use [`configure`](/atlas/modules/configure/).
- No discussion checkpoint or constellation path. The module does not load the companion `discuss` skill.

## Related CLI commands

- [`compile`](/atlas/reference/cli/compile/)
- [`memory-migrate`](/atlas/reference/cli/memory-migrate/)
- [`schema memory-rung`](/atlas/reference/cli/schema-memory-rung/)

## Related modules

- [`remember`](/atlas/modules/remember/) writes each page in an `apply` batch.
- [`schema`](/atlas/modules/schema/) is the only writer of `memory.rung`.
- [`migrate`](/atlas/modules/migrate/) relocates a store instead.
- [`configure`](/atlas/modules/configure/) installs and configures recall.
- [`mount`](/atlas/modules/mount/) resolves `root` first.
