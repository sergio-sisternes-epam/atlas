---
name: atlas/paths/query
description: Find and answer from an Atlas. Load before retrieval. Uses atlas search CLI; forbids unbounded tree grep as primary.
path_id: query
---

# Path: query

## When

Need knowledge from an Atlas (skill process memory or project store).

## Layers (do not merge)

| Name | Layer | Job |
|------|--------|-----|
| `path: query` | B17 protocol | Card, form the ask, search, rewrite once, select, read, hop, receipt |
| `atlas search` | CLI tool | Ranked hits + traffic payload |

Card `path` is always `query` for retrieval. The process is always `atlas search`. Do not add a peer path named search. The existing `atlas query` CLI alias remains search; do not invent a separate query engine. SCHEMA 2.0 recall (`--profile`, `--allow-partial`) is configured on path `configure`, not here.

## Enter (required — Atlas `activation_card: on`)

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: query
path_module: references/paths/query.md
intent: <one line>
root: <atlas store root>
```

Then **read this file**. Missing card or unloaded module ⇒ incomplete Enter.

Other paths (remember, work, landscape, an Autogenesis Run) may call `atlas search` as a **tool** under their own card. They still must not use unbounded tree grep as primary discovery.

## Procedure

1. **Resolve root** — load path `mount` first with `atlas_id` (and `ref`) on the card. Set `--root` to what `atlas resolve <atlas_id>` prints. Never `--root` the skill tree. Omitting `--root` uses the current working directory; the CLI does not default to the mount.
2. **Form the query** from the intent. Free text plus only justified field tokens:
   - `type:<name>` — frontmatter type, not a body mention
   - `kva:<value>` — traffic (alive, forming, terminated, …)
   - `status:<value>`
   - `work_id:<id>`
   - `path:<store-relative prefix>`
   Unknown `field:` tokens stay free text. Do not invent filters the ask does not support.
3. **Search (first)**
   ```bash
   python3 <atlas-skill>/scripts/atlas.py search "<query>" --root <root> --json
   ```
   Do **not** use unbounded whole-tree `grep` / `rg` / `find` as the primary discovery method. `rg` inside one already-chosen file is reading, not discovery.

   **Engine choice.** Grep is the basic default (`recall` off). After opt-in, `atlas:ranked` is the next configuration: published FTS5 plus cheap fingerprint (product bench ~80ms vs grep ~108ms on ~395 pages, and 4–13× cheaper follow-up reads). `atlas:tgrep` is advanced with limited benefits; do not enable it for latency (leaf `p-tgrep-serve-and-subset-rank`). Field filters beat an engine switch. Provenance: atlas-atlas lesson `lessons/2026-09-09-opt-in-ranked-after-fast-path.md` (experience `experiences/2026-09-09-smr-fast-path-product-bench.md`; leaf `p-query-engine-kpis`).
4. **Rewrite (at most once)** — if the question is synthesis / why / evolve / “all ideas”, **or** top hits only *mention* the token to exclude it, run **one** extra search. Extra tokens come only from the **Search aliases** table in `glossary.md` and from titles of pages already opened. Cap extra tokens (about 6). Keep the original question in the second query. Do not invent synonyms.
5. **Select hits from the payload** — prefer spine pages and `type: work` / `decision` for status, rules, names, or timelines; `experience` for what happened. Use `kva`, `status`, `work_id` on the hit. Pages with `kva`/`status` of `terminated` / `deprecated` / `superseded` are excluded by default; they appear only with `kva:terminated` (or `--include-exits`). Use them only to explain a dead frame.
6. **Read** 1–3 top pages (full body + frontmatter), including a spine or work hub when it ranks.
7. **Expand** via authoritative `relates_to` (`path` + `kind`) on the hit or page. Body `## Related` is only a mirror.
8. **Never** treat `staging/` as an answer source.
9. **Answer** from claims on those pages, citing paths. If nothing relevant → honest **gap**. After the one rewrite search, stop. A grep spiral is not allowed.

## Exit receipt

```text
skill: atlas
skill_path: …
path: query
root: …
search_cmd: atlas search "…" --root …
hits_used: <paths>
pages_read: <paths>
remember: no
compile: n/a
```

Claiming “checked the Atlas” without `search_cmd` ⇒ incomplete Exit.

## Non-goals

- Writing or compiling the store (use **remember** / **work**).
- OKF format rules (use skill **okf**).
- Treating compile `--type` as search.
