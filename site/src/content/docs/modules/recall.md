---
title: recall
description: Answer a question from an Atlas store by cueing a schema from the index and opening only the pages you need.
sidebar:
  order: 5
source:
  - references/paths/recall.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/recall.md: 652e1716ebe778169adf8b43ea3842cb65f6fa46
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `recall` module finds an answer in an Atlas store.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
`recall` is the formal lookup. It pairs the module with the `recall run` command.
The module is the protocol. The command is the tool. Do not merge the two names.

## When

Use `recall` when you need knowledge from an Atlas, such as a skill's process memory or a project store.
It applies even when you say "query" or "search".
There is no separate module called search.

Other modules, such as `remember`, `work` and `landscape`, may call the `recall run` command as a tool under their own card.
They still must not use an unbounded tree search as their main discovery method.

## What it does

1. **Resolve the root.** The agent loads [`mount`](/atlas/modules/mount/) first and uses the root that `resolve` prints.
   It never uses the skill tree as the root.
   Without `--root`, the CLI uses the current directory, not the mount.
2. **Cue from the index.** `index.md` is the folder's reserved directory listing. It is a list of *schema* cues.
   A schema is the top page that lists a folder's gists. It is not a table of contents and does not copy memory claims.
   Pages that the index does not cue are still searchable.
3. **Walk down only as far as needed.** The order is index, then schema, then *gist* (a short summary page), then *memory* (the full record).
   - If the schema answers, the agent stops there.
   - Otherwise it opens one relevant gist. If that answers, it stops.
   - It opens a memory page only when the gist does not answer, or the ask needs the record itself.
   - It does not load every gist for one ask.

   On shipped `SCHEMA.json` stores the top page is called a `frame`. On the current `CONTRACT.json` shape it is a `schema`.
   A *work hub* (`hub.md`) is not a level in this walk.
4. **Form the query.** The agent uses free text plus only the field tokens the ask justifies: `type:`, `kva:`, `status:`, `work_id:` and `path:`.
   Unknown field tokens stay free text. The agent does not invent filters.
5. **Search.** The agent always runs the search, even when the walk already answered:

   ```text
   python3 <atlas-skill>/scripts/atlas.py recall run "<query>" --root <root> --json
   ```

   Grep is the default engine while recall is off. After you opt in, `atlas:ranked` is the next configuration. `atlas:tgrep` is advanced and has limited benefits. Field filters help more than an engine switch.
6. **Rewrite at most once.** For a synthesis or "why" question, or when top hits only mention the term to exclude it, the agent runs one more search.
   Extra terms come only from the Search aliases table in `glossary.md` and from titles of pages already opened. The original question stays in the query.
7. **Select hits.** The agent prefers *spine* pages and `work` or `decision` pages for status, rules, names and timelines. It prefers `experience` pages for what happened.
   Pages marked `terminated`, `deprecated` or `superseded` are hidden by default. They appear with `kva:terminated` or `--include-exits`, and serve only to explain a dead line of thought.
8. **Read** one to three top pages in full, including a spine or work hub when it ranks.
9. **Expand** through the authoritative `relates_to` edges. A body `## Related` section is only a mirror.
10. **Never answer from `staging/`.** Staging is the store's short-lived holding area.
11. **Answer** from claims on those pages, with their paths. If nothing fits, the agent reports an honest gap. After the one rewrite, it stops.

The exit receipt records the root, the exact `recall run` command used (`recall_cmd`), the hits used, the pages read and where the walk stopped.
The stop level is `frame`, `schema`, `gist`, `memory`, `recall_hit` (an ordinary search answered) or `gap`.
Claiming "checked the Atlas" without `recall_cmd` makes the exit incomplete.

## How to ask for it

Ask a question about the store, for example "what does the Atlas say about our release process?" or "find the decision on storage strategy".
To learn about the module without running it, ask `/atlas help recall` or "explain recall".

## Activation card

The agent first emits [`mount`](/atlas/modules/mount/) to set `root`. Then it renders this card as a fenced `text` block:

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

The card `path` is always `recall` for retrieval. A missing card or an unloaded module means Enter is incomplete.

## Boundaries

- No unbounded whole-tree `grep`, `rg` or `find` as the main discovery method. Searching inside one chosen file is reading, not discovery.
- `staging/` never answers.
- At most one rewrite search. No search spiral.
- `recall` does not write or compile the store. Use [`remember`](/atlas/modules/remember/) or [`work`](/atlas/modules/work/).
- `recall` does not configure the recall index or SCHEMA 2.0 profiles (`--profile`, `--allow-partial`). Use [`configure`](/atlas/modules/configure/).
- Compile `--type` is not a discovery tool.
- OKF format rules belong to the companion `okf` skill.

## Related CLI commands

- [`recall run`](/atlas/reference/cli/recall-run/)
- [`resolve`](/atlas/reference/cli/resolve/)

## Related modules

- [`mount`](/atlas/modules/mount/) sets `root` first.
- [`remember`](/atlas/modules/remember/) and [`work`](/atlas/modules/work/) write to the store.
- [`landscape`](/atlas/modules/landscape/) may call `recall run` as a tool.
- [`configure`](/atlas/modules/configure/) sets up the recall index and profiles.
- [`atlas-recall`](/atlas/modules/atlas-recall/) navigates the memory layers by loading `recall`.
- [`help`](/atlas/modules/help/) and [`getting-started`](/atlas/modules/getting-started/) explain Atlas without formal recall.
