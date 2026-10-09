---
name: atlas/paths/recall
description: Use this path when an agent needs an answer from an Atlas store: cue a schema from index.md, then progressively open schema, gist, and memory pages, stopping as soon as the answer is present. Trigger on recall, find in the atlas, what does the store say, look up a decision or work hub, even when the user says query or search. Do not use it to write pages, compile, configure the recall index, or migrate memory layers. Invocation: FORCED when the Atlas router selects retrieval. Boundary: one path, one receipt field, no second index.
path_id: recall
---

# Path: recall

## When

Need knowledge from an Atlas (skill process memory or project store).

## Layers (do not merge)

| Name | Layer | Job |
|------|--------|-----|
| `path: recall` | B17 protocol | Card, form the ask, search, rewrite once, select, read, hop, receipt |
| `atlas recall run` | CLI tool | Ranked hits + traffic payload |

Card `path` is always `recall` for retrieval. The process is always `atlas recall run`. Do not add a peer path named search. SCHEMA 2.0 recall (`--profile`, `--allow-partial`) is configured on path `configure`, not here.

## Enter (required — Atlas `activation_card: on`)

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: recall
path_module: references/paths/recall.md
intent: <one line>
root: <atlas store root>
```

Then **read this file**. Missing card or unloaded module ⇒ incomplete Enter.

Other paths (remember, work, landscape, an Autogenesis Run) may call `atlas recall run` as a **tool** under their own card. They still must not use unbounded tree grep as primary discovery.

## Procedure

1. **Resolve root** — load path `mount` first with `atlas_id` (and `ref`) on the card. Set `--root` to what `atlas resolve <atlas_id>` prints. Never `--root` the skill tree. Omitting `--root` uses the current working directory; the CLI does not default to the mount.
2. **Cue from the index** — `index.md` is the OKF reserved directory listing and hot schema-cue list, not laboratory short-term memory (Cowan STM) and not a table of contents. Read its schema cues before opening a schema. It does not copy memory claims or pin every gist; pages not cued there remain searchable. Index and `hub.md` filenames stay unsuffixed, and a work hub is not a memory level.
3. **Progressive disclosure (index → schema → gist → memory)** — open the schema cued for the question. If it answers, stop: do not open a gist or memory page. Otherwise open only a relevant gist; if it answers, stop without opening its parent memory. Descend to a memory page only when the gist does not answer or the ask needs the record itself. Do not load every gist for one ask. On shipped `SCHEMA.json` stores, the first memory-layer page is named `frame`; on the current `CONTRACT.json` shape it is `schema`. On either shape, stop at the level in hand when it answers and do not open a lower level after a hit.
4. **Form the query** from the intent. Free text plus only justified field tokens:
   - `type:<name>` — frontmatter type, not a body mention
   - `kva:<value>` — traffic (alive, forming, terminated, …)
   - `status:<value>`
   - `work_id:<id>`
   - `path:<store-relative prefix>`
   Unknown `field:` tokens stay free text. Do not invent filters the ask does not support.
5. **Search (always run, even when the gist already answered)**
   ```bash
   python3 <atlas-skill>/scripts/atlas.py recall run "<query>" --root <root> --json
   ```
   Run this step regardless of whether the hot list or abstraction walk already answered the ask — the exit receipt always records `recall_cmd`. Stopping at the gist (step 3) decides whether the parent memory page is opened, not whether search runs.
   Do **not** use unbounded whole-tree `grep` / `rg` / `find` as the primary discovery method. `rg` inside one already-chosen file is reading, not discovery.

   **Engine choice.** Grep is the basic default (`recall` off) and stays the default when no flag is passed. With `recall` off, `--engine bm25` ranks with SQLite FTS5: it reuses a published generation when the cheap fingerprint matches, otherwise it builds a temporary index and deletes it after the query. It falls back to grep with a warning only when FTS5 is unavailable or projection fails. In both `--engine bm25` and FTS5 presets such as `atlas:ranked`, if an all-words query finds nothing, one any-word retry runs; the payload says `match: "any"` and so does each retried hit, so treat those hits as weaker evidence. After opt-in, `atlas:ranked` is the next configuration: published FTS5 plus cheap fingerprint (product bench ~80ms vs grep ~108ms on ~395 pages, and 4–13× cheaper follow-up reads). `atlas:tgrep` is advanced with limited benefits; do not enable it for latency (leaf `p-tgrep-serve-and-subset-rank`). Field filters beat an engine switch. Provenance: atlas-atlas lesson `lessons/2026-09-09-opt-in-ranked-after-fast-path.md` (experience `experiences/2026-09-09-smr-fast-path-product-bench.md`; leaf `p-query-engine-kpis`).
6. **Rewrite (at most once)** — if the question is synthesis / why / evolve / “all ideas”, **or** top hits only *mention* the token to exclude it, run **one** extra search. Extra tokens come only from the **Search aliases** table in `glossary.md` and from titles of pages already opened. Cap extra tokens (about 6). Keep the original question in the second query. Do not invent synonyms.
7. **Select hits from the payload** — prefer spine pages and `type: work` / `decision` for status, rules, names, or timelines; `experience` for what happened. Use `kva`, `status`, `work_id` on the hit. Pages with `kva`/`status` of `terminated` / `deprecated` / `superseded` are excluded by default; they appear only with `kva:terminated` (or `--include-exits`). Use them only to explain a dead frame.
8. **Read** 1–3 top pages (full body + frontmatter), including a spine or work hub when it ranks.
9. **Expand** via authoritative `relates_to` (`path` + `kind`) on the hit or page. Body `## Related` is only a mirror. `atlas graph neighbours <page> --root <root> --json` gives the same `relates_to` expansion as structured JSON (direction, kind and hop per edge); see `references/graph.md`.
10. **Never** treat `staging/` as an answer source.
11. **Answer** from claims on those pages, citing paths. If nothing relevant → honest **gap**. After the one rewrite search, stop. A grep spiral is not allowed.

## Exit receipt

```text
skill: atlas
skill_path: …
path: recall
root: …
recall_cmd: atlas recall run "…" --root …
hits_used: <paths>
pages_read: <paths>
stopped_at: frame | schema | gist | memory | recall_hit | gap
opened_page_reason: <present only when a page is opened>
remember: no
compile: n/a
```

`stopped_at: recall_hit` means the answer came from ordinary search rather than
the progressive memory walk. `stopped_at: gap` means an honest gap — nothing
relevant was found. `stopped_at: frame` is the shipped `SCHEMA.json` name;
`stopped_at: schema` is the current `CONTRACT.json` name. A hub is never a stop
level in this walk.

Claiming “checked the Atlas” without `recall_cmd` ⇒ incomplete Exit.

## Non-goals

- Writing or compiling the store (use **remember** / **work**).
- OKF format rules (use skill **okf**).
- Treating compile `--type` as recall discovery.
