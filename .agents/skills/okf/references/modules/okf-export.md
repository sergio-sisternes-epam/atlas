---
name: okf-export
description: Produce a portable Open Knowledge Format v0.2 bundle from the live Atlas knowledge store. Trigger on export Atlas, export knowledge store, export as OKF, create OKF bundle, download knowledge bundle.
---

# OKF Export

Produce a portable Open Knowledge Format v0.2 bundle from the live Atlas knowledge store.

## Process

1. Read the live Atlas store (`atlas mount github.com/sergio-sisternes-epam/okf-atlas`; compile/query root `.../okf-atlas/atlas`).
2. Ensure every concept page under `pages/` (or equivalent) has valid OKF frontmatter (at minimum a `type` field). If a page is missing frontmatter, add a minimal compliant one before export (do this on the export copy only).
3. Create an export directory under the harness artifacts area, e.g. `artifacts/okf-export/YYYY-MM-DD-HHMM-atlas-bundle/`.
4. Copy / transform:
   - concept pages → concept files (preserve structure, ensure frontmatter)
   - `index.md` and `log.md` (OKF-reserved files)
   - Optionally include a short `README.md` describing the bundle
5. Convert any remaining `[[wikilink]]` style references into OKF absolute links where possible.
6. Validate the bundle against the core OKF rules (load `okf-authority` via the substrate contract).
7. Optionally create a `.zip` or `.tar.gz` of the bundle for easy download.
8. Report the export path and a short summary of what was exported.

## Rules

- Always load the `okf-authority` module (or the parent `okf` skill) for format rules, using the substrate contract below.
- Never modify the live Atlas store during export (work on a copy).
- For live knowledge-store structure, use Atlas (`atlas mount github.com/sergio-sisternes-epam/okf-atlas`; compile/query root `.../okf-atlas/atlas`). Do not use `okf-wiki` for new process memory.

## Substrate contract (mandatory for every skill or module load)

When this body must invoke / load / execute another skill (or one of its progressive modules):

1. Locate the target skill **by name** from the harness’s available skills list (do not hard-code absolute paths).
2. Load the **full body** of that skill’s entrypoint (`SKILL.md`) using the harness’s on-demand skill-loader tool. Never rely on the short frontmatter description alone.
3. Follow the loaded body instructions **exactly**.
4. Re-execute any live tool calls the body requires.

For internal progressive-disclosure modules under `references/modules/`, locate the parent skill first, then `read_file` the module path relative to that skill root (or follow the loaded parent body’s own progressive-disclosure instructions).
