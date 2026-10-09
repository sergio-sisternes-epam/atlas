---
name: atlas/paths/remember
description: Persist claim-bearing knowledge into an Atlas and leave compile green. Load before writing experiences, decisions, lessons, recipes.
path_id: remember
---

# Path: remember

## When

Capture an experience, decision, lesson, recipe, or other durable concept into an
Atlas. `document` is an existing legacy type that remains valid to read; it is not
a recommended choice for new writes.

## Enter

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

## Procedure

1. **Resolve root** (same as recall — path `mount`). If there is no active git repository, **stop**. Do not persist.
2. **Wrong-frame trigger** — if the user explicitly kills a comparison or thesis (“wrong comparison”, “that is not what Atlas is”, “terminate this branch”, “KVA terminate”), do **not** keep writing the dead matrix. Load catalog skill **discuss** (substrate contract) and path `references/paths/terminate.md`. Pass `atlas_root` = this root, `subject_node`, and `living_node`. Return to remember only for living pages terminate asked you to author. Recipe: `references/recipes/terminate-wrong-path.md`.
   - **Thoughtful current-theory** — if the pages are `lesson`, live `decision`, or `recipe`, first think a designed inventory (path, type, one-line claim, source URIs). The remember card from Enter is enough; do not emit a second card. Persist may then proceed **without** human approval. If the human has asked for review on this persist (or named it important / hold for approval), show the inventory and **stop** until they approve or cut the set. Episodic `experience` and discussion-graph types are not this step. Recipe: `references/recipes/gated-memory-building.md`.
3. **Detect contract shape, then choose type and path** — read the store's root contract file first (`CONTRACT.json` if present, else `SCHEMA.json`; exactly one of the two exists). On the current `CONTRACT.json` shape (stamped `0.13.0`, or an older accepted `0.13.0-beta.3`/`beta.4`/`beta.7` stamp), recommended types are `experience`, `decision`, `lesson`, `recipe`, `work`, `protostar`, `memory`, `gist`, `schema` (`schema` is the renamed `frame`; do not recommend `frame` on this shape). On a shipped `SCHEMA.json` shape, the episode type name depends on which beta it is — check `atlas_release` first, then `memory.layers` shape:
   - **0.13.0-beta.2** — recommended when `atlas_release` is exactly `0.13.0-beta.2`, OR `memory.layers` is `["frame", "gist", "memory"]`, OR it is an unstamped full beta.2 init (no `atlas_release`, no `memory` object at all, but templates plus `types.recommended` including `frame`). Recommended types: `experience`, `decision`, `lesson`, `recipe`, `work`, `protostar`, `memory`, `gist`, `frame`. Do not recommend `page` on this shape.
   - **Original 0.13.0-beta** — recommended when `atlas_release` is exactly `0.13.0-beta`, OR `memory.layers` is `["frame", "gist", "page"]`, OR `atlas_release` is absent and the document is **not** the unstamped full beta.2 init described above. Recommended types: `experience`, `decision`, `lesson`, `recipe`, `work`, `protostar`, `page`, `gist`, `frame`. Do not recommend `memory` on this shape.

   `document` is an existing legacy type that remains valid to read; it is not a recommended choice for new writes on any shape. Recommended frontmatter: `origin` (internal|third-party|user|derived), `sensitivity` (public|internal|restricted). A protostar is a forming idea (`kva: forming`, `growth: true`) parked beside its origin; never a `residuals/` folder.
4. **Write** a claim-bearing page (frontmatter + body). Or:
   - `atlas migrate <source> --root <root>` into staging only, then
   - `atlas promote <staging-file> --to <target> [--type …] --root <root>`, then
   - complete claims (promote only scaffolds).
5. **relates_to (authoritative)** — list `{path, kind}` edges. Recommended kinds: `follows`, `records`, `supersedes`, `implements`, `derived_from`, `related`.
6. **Work cluster** — if the page has a `work_id`, include:
   ```yaml
   - path: work/<work_id>.md
     kind: implements
   ```
   (or `autogenesis/work/<work_id>.md` when the subject uses Autogenesis space) and ensure the work hub exists (create via **work** path if needed). Protostars also `relates_to` their origin page with `kind: derived_from`.
7. **Write model and layers** — one writer owns a folder; do not rewrite sibling schemas. The four-layer climb is optional. A page may be indexed with or without a schema, and a memory or other type may omit a gist. Non-memory types stay index-first-class: do not invent a typed middle extension for them. Do not refuse a remember solely because a middle rung is absent. A new or contradicted memory may cascade upward to an owning gist and schema when evidence supports that gist. Gists are filed beside their same-folder `derived_from` parents (one, or several when those parents already form one cluster). They are never derived from a work hub, plan, index, another gist, or a schema/frame, and cross-folder `relates_to` does not join a cluster. On the current `CONTRACT.json` shape, every folder gist must be listed by at least one same-folder `type: schema` page using `relates_to` kind `related`; multiple schemas are legal and each lists its own gists. Schema is required because a gist was created, not because a page was indexed. When the subject of the live branch changes, create another schema rather than rewriting an unrelated sibling: name it `<name>.schema.md`, link schema-to-schema to the prior schema, and list the new schema from `index.md`. Keep `hub.md` in place; it is a work hub, not a memory page or a rung in recall. The index lists schema cues when a schema exists, not memory copies or every gist as a hot list. Links between layers stay same-level (schema–schema, gist–gist, memory–memory); parent/child relationships use the specified `related` or `derived_from` edge. A non-empty gist `description` must appear as an exact substring in the body or description of at least one memory page it derives from; otherwise current-shape compile reports `stale_upper_page`. Before writing a gist, scan the text you would copy: critical or high secret-class text, or `sensitivity: restricted`, refuses the gist; a medium `booking_manage_reference` is a handoff, not a written gist. Never invent a gist body or write a title-only stub to clear `missing_gist`. On shipped `SCHEMA.json` stores, retain existing `frame`/`gist`/`page` or `memory` type names and the shipped `frame_members` ladder; do not impose the current-shape schema gate there.
   For the original 0.13.0-beta shape, gist parents include `page`; for 0.13.0-beta.2 they include `memory` (see step 3 for the full shape-specific type list). The current `CONTRACT.json` shape uses `schema`, `gist`, and `memory`.
   **Suffixes are search handles, not types:** create current-shape pages as `<name>.schema.md`, `<name>.gist.md`, or `<name>.memory.md`. Frontmatter `type` remains `schema`, `gist`, or `memory` and is the contract type. Keep shipped-beta `SCHEMA.json` page type names unchanged.
8. **Spine pages** — if the new page belongs to a cluster that already has a short index (work hub Outcomes, or a document titled as an evolution / “all ideas” spine), add a `relates_to` edge and a one-line claim on that spine. Do not copy the essay onto the spine.
9. **Compile** — run before touching any index:
   ```bash
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```
   - **Index-only** means every critical finding id is `schema_missing_from_index` and every warning finding id is `index_md_present` (missing folder or root `index.md`); either list may be empty. If all findings are index-only and the exit is non-zero, proceed to step 10, including exit 2 when `schema_missing_from_index` is critical. Waiting for exit 0 first deadlocks the required schema cue.
   - If any critical finding id is not `schema_missing_from_index`, or any warning id is not `index_md_present`, fix those first; do **not** edit `index.md` yet and do **not** claim memory stored.
   - Exit 0 → proceed to step 10 when a gist needs a hot-list pin.
10. **Index** — create the owning folder's `index.md` if it is missing, then add or update a cue for the owning schema. Do not copy the memory claim or pin every gist on the index. Path `recall` reads the schema cues; it never writes them.
11. **Compile again** — must exit 0 after the index edit before claiming memory stored:
   ```bash
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```
   Exit ≠ 0 → fix critical issues; do **not** claim memory stored.
12. **log.md** — append one bullet only for **structural** changes (new/closed work, layout migration, schema shift). Not for every experience.

## Exit

- Paths written + `atlas compile` exit 0.
- Incomplete if compile red, staging non-empty, or required work hub edge missing.

## Non-goals

- Answering questions (use **recall**).
- Opening/closing work status alone (use **work**; remember may create pages under an existing hub).
