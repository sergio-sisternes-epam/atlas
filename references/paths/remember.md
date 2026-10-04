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
3. **Choose type and path** — recommended types: `experience`, `decision`, `lesson`, `recipe`, `work`, `protostar`, `memory`, `gist`, `frame` (and folder conventions under SCHEMA). `document` is an existing legacy type that remains valid to read; it is not a recommended choice for new writes. Recommended frontmatter: `origin` (internal|third-party|user|derived), `sensitivity` (public|internal|restricted). A protostar is a forming idea (`kva: forming`, `growth: true`) parked beside its origin; never a `residuals/` folder.
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
7. **Gists and frames** — a gist is filed in the same folder as its one parent and `relates_to` that parent with `kind: derived_from`. Parents are `experience`, `decision`, `lesson`, `recipe`, `document`, `memory`, or `protostar` — never a work hub, plan, index, another gist, or a frame. Every folder with one or more gist files has exactly one frame in that same folder; its `relates_to` kind `related` lists exactly the gist paths in that folder, each once. A lone gist still gets a frame; a folder with no gists has no frame. Do not require `gists/` or `frames/` directories. A frame does not rewrite its gists. Do not rewrite an episodic parent page in place to match a gist or a frame — the parent stays the record. This rule describes shipped `SCHEMA.json` stores (0.13.0-beta and 0.13.0-beta.2, memory episode type `memory`). On the 0.13.0-beta.3 write model (`CONTRACT.json`), `schema` is the renamed `frame`; the same one-gist-counts, folder-scoped rule applies unchanged.
8. **Spine pages** — if the new page belongs to a cluster that already has a short index (work hub Outcomes, or a document titled as an evolution / “all ideas” spine), add a `relates_to` edge and a one-line claim on that spine. Do not copy the essay onto the spine.
9. **Compile** — run before touching any index:
   ```bash
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```
   - Exit 2 (critical) → fix; do **not** edit `index.md` yet and do **not** claim memory stored.
   - Exit 1 solely from **index-only** findings (`index_md_present` / missing folder or root `index.md`) → proceed to step 10. That finding is why the index is created; waiting for exit 0 first deadlocks a new gist in a folder that has no `index.md` yet.
   - Exit 1 from any other actionable warning → fix those first; do **not** edit `index.md` yet and do **not** claim memory stored.
   - Exit 0 → proceed to step 10 when a gist needs a hot-list pin.
10. **Index** — create the owning folder's `index.md` if it is missing, then insert the new gist at the top of that hot list (top, not bottom). Path `recall` reads that list; it never writes it.
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
