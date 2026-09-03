---
name: atlas/paths/remember
description: Persist claim-bearing knowledge into an Atlas and leave compile green. Load before writing experiences, decisions, lessons, recipes, documents.
path_id: remember
---

# Path: remember

## When

Capture an experience, decision, lesson, recipe, document, or other durable concept into an Atlas.

## Enter

Prefer activation card with `path: remember`, `path_module: references/paths/remember.md`, and `root: <atlas root>`.

## Procedure

1. **Resolve root** (same as query — path `mount`). If there is no active git repository, **stop**. Do not persist.
2. **Wrong-frame trigger** — if the user explicitly kills a comparison or thesis (“wrong comparison”, “that is not what Atlas is”, “terminate this branch”, “KVA terminate”), do **not** keep writing the dead matrix. Load catalog skill **discuss** (substrate contract) and path `references/paths/terminate.md`. Pass `atlas_root` = this root, `subject_node`, and `living_node`. Return to remember only for living pages terminate asked you to author. Recipe: `references/recipes/terminate-wrong-path.md`.
   - **Thoughtful current-theory** — if the pages are `lesson`, live `decision`, or `recipe`, first think a designed inventory (path, type, one-line claim, source URIs). The remember card from Enter is enough; do not emit a second card. Persist may then proceed **without** human approval. If the human has asked for review on this persist (or named it important / hold for approval), show the inventory and **stop** until they approve or cut the set. Episodic `experience` and discussion-graph types are not this step. Recipe: `references/recipes/gated-memory-building.md`.
3. **Choose type and path** — recommended types: `experience`, `decision`, `lesson`, `recipe`, `work`, `document`, `protostar` (and folder conventions under SCHEMA). Recommended frontmatter: `origin` (internal|third-party|user|derived), `sensitivity` (public|internal|restricted). A protostar is a forming idea (`kva: forming`, `growth: true`) parked beside its origin; never a `residuals/` folder.
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
7. **Spine pages** — if the new page belongs to a cluster that already has a short index (work hub Outcomes, or a document titled as an evolution / “all ideas” spine), add a `relates_to` edge and a one-line claim on that spine. Do not copy the essay onto the spine.
8. **Compile** — must succeed:
   ```bash
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```
   Exit ≠ 0 → fix critical issues; do **not** claim memory stored.
9. **log.md** — append one bullet only for **structural** changes (new/closed work, layout migration, schema shift). Not for every experience.

## Exit

- Paths written + `atlas compile` exit 0.
- Incomplete if compile red, staging non-empty, or required work hub edge missing.

## Non-goals

- Answering questions (use **query**).
- Opening/closing work status alone (use **work**; remember may create pages under an existing hub).
