---
title: remember
description: Write claim-bearing knowledge into an Atlas store and finish only when compile is green.
sidebar:
  order: 6
source:
  - references/paths/remember.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/remember.md: 38e7c68622427c324d16119b3da62ad2473c3059
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `remember` module writes durable knowledge into an Atlas store.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
A write counts only when the `compile` command exits 0.
*Compile* checks the store's contract shape, required frontmatter and required links.

## When

Use `remember` to capture an experience, decision, lesson, recipe or other durable concept.
`document` is a legacy type. It stays valid to read, but it is not a recommended choice for new writes.

## What it does

1. **Resolve the root.** The agent loads [`mount`](/atlas/modules/mount/) first, as for recall. With no active git repository, it stops and persists nothing.
2. **Check for a wrong frame.** If you explicitly kill a comparison or thesis, the agent stops writing it.
   It loads the companion `discuss` skill and its terminate path instead. It returns to `remember` only for the living pages that terminate asks for.
3. **Design an inventory for current-theory pages.** Before it writes a `lesson`, a live `decision` or a `recipe`, the agent drafts an inventory: path, type, one-line claim and source URIs.
   Your approval is not a default gate. If you asked to review this write, the agent shows the inventory and waits.
4. **Detect the contract shape, then choose type and path.** The agent reads the store's single contract file: `CONTRACT.json` if present, else `SCHEMA.json`.
   - On the current `CONTRACT.json` shape, recommended types include `memory`, `gist` and `schema`. `schema` replaces `frame` here.
   - On a shipped `SCHEMA.json` store, the agent checks `atlas_release`, then `memory.layers`. A 0.13.0-beta.2 store uses `memory`, `gist` and `frame`. An original 0.13.0-beta store uses `page`, `gist` and `frame`.
   - All shapes also recommend `experience`, `decision`, `lesson`, `recipe`, `work` and `protostar`.
   - A *protostar* is a forming idea (`kva: forming`, `growth: true`) parked beside its origin page.
5. **Write** a claim-bearing page with frontmatter and body.
   Or the agent copies a source into *staging* (the store's short-lived holding area), promotes it to a target path, and then completes the claims. Promote only scaffolds a page.

   ```text
   python3 <atlas-skill>/scripts/atlas.py migrate <source> --root <root>
   python3 <atlas-skill>/scripts/atlas.py promote <staging-file> --to <target> [--type <type>] --root <root>
   ```

6. **Add `relates_to` edges.** Each edge has a `path` and a `kind`: `follows`, `records`, `supersedes`, `implements`, `derived_from` or `related`. These edges are authoritative.
7. **Link the work cluster.** A page with a `work_id` links `work/<work_id>.md` with `kind: implements`. The *work hub* must exist; the agent creates it through [`work`](/atlas/modules/work/) if needed. A protostar links its origin with `kind: derived_from`.
8. **Respect the write model and layers.**
   - One writer owns a folder. The agent does not rewrite sibling schemas.
   - The four-layer climb is optional. A page may skip the gist or the schema.
   - A *gist* is a short page filed beside its same-folder `derived_from` memory parents. It never derives from a work hub, plan, index, another gist or a schema.
   - On the current shape, at least one same-folder `schema` page lists every gist with kind `related`.
   - When the live subject changes, the agent adds a new `<name>.schema.md`, links it to the prior schema and lists it in `index.md`.
   - A non-empty gist `description` must appear exactly in the body or description of a parent memory page. Otherwise compile reports `stale_upper_page`.
   - The agent refuses a gist that would copy critical or high secret-class text, or `sensitivity: restricted` text. It never invents a gist body or a title-only stub.
   - The suffixes `.schema.md`, `.gist.md` and `.memory.md` are search handles. Frontmatter `type` stays authoritative.
   - On shipped `SCHEMA.json` stores, the agent keeps the shipped type names and `frame_members` ladder.
9. **Update spine pages.** If the cluster already has a short index page, the agent adds an edge and a one-line claim there. It does not copy the essay.
10. **Compile before touching any index:**

    ```text
    python3 <atlas-skill>/scripts/atlas.py compile --root <root>
    ```

    If the only findings are `schema_missing_from_index` criticals or `index_md_present` warnings, the agent moves on to the index, even at exit 2. Waiting for exit 0 would deadlock.
    Any other finding must be fixed first.
11. **Update the index.** The agent creates the folder `index.md` if missing and adds a cue for the owning schema. It does not copy memory claims or pin every gist.
12. **Compile again.** It must exit 0 before the agent claims the memory is stored.
13. **Append to `log.md`** only for structural changes, such as new or closed work, a layout migration or a schema shift.

The exit lists the paths written and a compile exit of 0.
The run is incomplete if compile is red, `staging/` is not empty, or a required work hub edge is missing.

## How to ask for it

Ask the agent to record something, for example "remember this decision in the Atlas" or "capture a lesson from this incident".
To review an important write first, say so. The agent then stops after the inventory.
To learn about the module without running it, ask `/atlas help remember` or "explain remember".

## Activation card

The agent first emits [`mount`](/atlas/modules/mount/) to set `root`. Then it renders this card as a fenced `text` block:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: remember
path_module: references/paths/remember.md
intent: <one line>
root: <atlas store root>
```

This one card also covers current-theory writes. The agent does not emit a second card.

## Boundaries

- No git repository means no persistence.
- No claim of "stored" until compile exits 0.
- `staging/` must be empty at the end.
- No `residuals/` folder for protostars.
- No invented gists or title-only stubs.
- No manual edits to the contract file or `schema.d/`. Use [`schema`](/atlas/modules/schema/).
- `remember` does not answer questions. Use [`recall`](/atlas/modules/recall/).
- `remember` does not open or close work status alone. Use [`work`](/atlas/modules/work/).

## Related CLI commands

- [`compile`](/atlas/reference/cli/compile/)
- [`migrate`](/atlas/reference/cli/migrate/)
- [`promote`](/atlas/reference/cli/promote/)
- [`resolve`](/atlas/reference/cli/resolve/)

## Related modules

- [`mount`](/atlas/modules/mount/) sets `root` first.
- [`recall`](/atlas/modules/recall/) answers questions from the store.
- [`work`](/atlas/modules/work/) opens and closes work hubs.
- [`atlas-memorise`](/atlas/modules/atlas-memorise/) chooses the layer before it loads `remember`.
