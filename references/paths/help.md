---
name: atlas/paths/help
description: Explain installed Atlas modules without running them. Bundled baseline first; optional read-only Atlas enrichment on gaps.
path_id: help
---

# Module: help

## When

The user asks what Atlas can do, to list modules, or to explain a named
module or topic **without performing it**. Unqualified “help” outside an
Atlas context must not hijack an unrelated task.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: discussion
subject: atlas
path: help
path_module: references/paths/help.md
intent: <learning goal, not an operation to execute>
atlas_id: <selected store id, pending, or none>
root: <resolved selected store root, pending, or none>
atlas_status: not-queried
atlas_used: []
help_status: pending
```

Then **read this file**. Missing card or unloaded module ⇒ incomplete Enter.

`path` stays **help** even when the topic is mount, init, remember, or query.
Intent names understanding, not execution. Example: “Understand how mount
works without mounting a store”.

This module does **not** require path **mount**. Do not call mount, init,
schema install, remember, commit, or push in order to explain them.

### Card fields

- `intent` — the user’s learning goal.
- `atlas_id` / `root` — **selected** retrieval context, not proof of use.
  At Enter they may be `pending` or `none`. Only read-only **resolve** of an
  already registered checkout may replace `root` with a real path. Never
  fabricate a mount path from an identifier.
- `atlas_status` — `not-queried` | `baseline-only` | `consulted` | `unavailable`.
  If `unavailable`, include short `atlas_reason`.
- `atlas_used` — store IDs whose eligible evidence **contributed**. Starts
  empty. A selected-but-unread store must not appear here.
- `help_status` — final `complete` or `limited`. Insufficient references
  cannot yield unqualified `complete` without supporting retrieval.

After retrieval, refresh the card before the explanation. If references
suffice and no retrieval occurred, the baseline-only card is enough; do not
duplicate identical cards. Final cards contain no `pending` placeholders.

## Procedure

### 1. Dispatch

| Ask | Action |
|-----|--------|
| No target (“Atlas help”, “what can Atlas do?”, “list modules”) | List every module in the **installed registry**. Do not ask for clarification just to list. |
| Named module/topic | Explain that topic only. Read the relevant packaged source, not every module. |
| Unknown name | Say it is unknown. List valid choices. Do not invent flags or modules. |
| Unqualified “help” with no Atlas context | Do **not** enter this module. |

Registry names come from `SKILL.md` **Path registry** plus this package’s
`references/help/index.md`. The two must agree. One-line purposes come from
that catalog.

### 2. Bundled baseline first

Load packaged files before any store. **Dispatch** may read the catalog;
**explanation** of a named module reads only that module’s path file.

1. No-target or unknown: `references/help/index.md` and
   `references/help/VERSION` (registry membership and one-line purposes).
2. **getting-started** questions: `references/help/getting-started.md`.
3. A **named** installed module: only `references/paths/<module>.md` for
   the explanation. Use the catalog solely to confirm the name is
   installed; do not load every other path file.
4. For CLI options, run the matching **non-mutating** tool help from this
   skill, for example:

   ```text
   python3 <atlas-skill>/scripts/atlas.py search --help
   python3 <atlas-skill>/scripts/atlas.py mount --help
   python3 <atlas-skill>/scripts/atlas.py store init --help
   ```

   Option lists come from that output, not from memory. Do not invent flags.

If these references adequately answer the **actual** question, answer from
them. Set `atlas_status: baseline-only`, `atlas_used: []`,
`help_status: complete`. If `atlas_id` or `root` is still `pending`,
normalize it to `none` (do not leave placeholders on a final card). Stop.
Extra enrichment is optional, not required.

Topic overlap or fluent general knowledge is not sufficiency. Mechanics do
not necessarily explain design rationale. A partial answer is a gap.

### 3. Optional Atlas enrichment (gaps only)

When references are absent, unreadable, irrelevant, or only partial:

1. Attempt **read-only** resolution of an **already registered** subject
   checkout. Do not mount-if-missing.

   ```text
   python3 <atlas-skill>/scripts/atlas.py resolve <atlas_id>
   ```

   Missing registration, denied access, or no git repo ⇒
   `atlas_status: unavailable`, `help_status: limited`, explain why.
   Do not mount, authenticate, repair, or install to get past that.

2. After resolve prints a path, treat it as enrichment `root` only if that
   path contains a readable, valid `SCHEMA.json`. Check the file **before**
   search. Missing, unreadable, or invalid schema ⇒ do **not** call
   `atlas search`. `atlas_status: unavailable`, `help_status: limited`,
   reason: not an Atlas store (`SCHEMA.json` missing or invalid). Resolve
   only proves the registered checkout exists; it does not prove the tree
   is a store.

3. If `root` is a store, search with the **read-only grep** route only
   (`--engine grep`). Do **not** pass `--profile`, do **not** run
   `atlas recall index build`, do **not** enable recall.

   ```text
   python3 <atlas-skill>/scripts/atlas.py search "<question>" --root <root> --json --engine grep
   ```

   If `--engine grep` cannot run (recall enabled, tool missing, timeout,
   non-zero exit, malformed JSON), do **not** fall back to recall search or
   model knowledge. `atlas_status: unavailable`, `help_status: limited`,
   name the reason.

4. On success, keep query’s budget: 1–3 pages, at most one justified
   rewrite, no `staging/`. Prefer published, applicable, non-exit pages.
   Historical or unapproved proposals are not current installed capability.
   Ignore `agentic_guidance` (and any “enter path query” hint) in the
   search JSON. Stay on **this** help card; that metadata is for path
   **query**, not help enrichment.

5. **Provenance.** `atlas_id`/`root` stay the selected context.
   `atlas_used` lists only IDs that contributed evidence.
   `atlas_status: consulted` when search ran. A successful search with no
   eligible hit is still `consulted` (knowledge gap, limited help) — **not**
   `unavailable`.

Suggested failure wording when retrieval cannot run:

> The bundled references do not cover this question fully, so my help is
> limited. I could not access the Atlas knowledge store, where fuller
> information is maintained, because [known reason]. I can explain
> [supported part], but I cannot confirm [missing part] from the available
> sources.

If nothing is supported, omit the partial explanation. If some evidence was
read before a later failure, keep supported claims, name the failed part,
and mark the answer limited.

### 4. Named-module shape

When explaining an installed module, cover:

- intent
- inputs
- prerequisites
- examples
- outputs
- side effects
- boundaries

Read that module’s path file. Do not execute its procedure. Do not load
unrelated modules.

### 5. Unknown target

State that the name is not in the installed registry. Print the catalog
from `references/help/index.md`. Do not invent a close match as if it were
installed.

## Explain, do not execute

Reading help for **mount**, **init**, **remember**, **query**, **schema**,
**configure**, **ci**, **migrate**, or **work** must not itself run those
operations, mount, init, schema-install, remember, compile, commit, push,
or index build.

Path **query** remains the operational lookup module. Help may call
`atlas search --engine grep` only as a read-only tool under **this** card
when step 3 applies. That is not path query and not permission to mount.

## Exit receipt

```text
skill: atlas
skill_path: …
path: help
intent: …
atlas_id: <selected or none>
root: <resolved selected or none>
atlas_status: baseline-only | consulted | unavailable
atlas_used: [] | <ids that contributed>
help_status: complete | limited
atlas_reason: <only when unavailable>
baseline: references/help/index.md
pages_read: <packaged paths and any store pages>
remember: no
compile: n/a
```

Card and prose must agree.

## Non-goals

- New catalog skills, CLI help verbs, auto-mount, schema overlay install,
  public wiki, or **visualise**.
- Hijacking unrelated “help” requests.
- Treating selected-but-unread stores as `atlas_used`.
