---
name: atlas/paths/getting-started
description: First-use Atlas guidance. Explain purpose, prerequisites, first journey, and storage choices without creating a store.
path_id: getting-started
---

# Module: getting-started

## When

The user is new to Atlas, asks how it works, how to start, or where knowledge
can live. Explain. Do not execute init, mount, query, or remember.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: discussion
subject: atlas
path: getting-started
path_module: references/paths/getting-started.md
intent: Learn what Atlas does and choose a first useful step
atlas_id: none
root: none
atlas_status: not-queried
atlas_used: []
help_status: pending
```

Then **read this file**. Missing card or unloaded module ⇒ incomplete Enter.
`path` stays `getting-started`. Never label this card as `init` or `mount`.

This module does **not** require path **mount**. `atlas_id` / `root` name the
selected retrieval context if enrichment is later required; they are not
proof a store was used.

## Procedure

1. **Load the bundled baseline** — read
   `references/help/getting-started.md` and `references/help/index.md` from
   this skill package (`package_version` in those files / `references/help/VERSION`).
   Do not mount. Do not init. Do not search a store yet.
2. **Answer first-use from the baseline** when it covers the ask:
   purpose, prerequisites, marketplace install, shortest useful journey,
   **equal** storage choices (existing-repo branch vs dedicated existing
   repo; never prefer creating a new repo), then point at **help**.
3. **Sufficiency.** Topic overlap is not enough. If the ask exceeds the
   baseline (rationale, history, a named module’s side effects), follow
   module **help** for that remainder: same read-only retrieval rules, same
   card fields. Do not execute the leftover module.
4. **Card refresh.** If the baseline fully answers and no retrieval ran,
   set `atlas_status: baseline-only`, `atlas_used: []`, `help_status: complete`,
   keep `atlas_id`/`root` as `none`. Do not duplicate an identical card.
   If enrichment ran, refresh before the explanation with final
   `atlas_status`, resolved `root`, and `atlas_used` listing only stores
   whose evidence contributed. Final cards contain no `pending`.
5. **Stop.** Suggest next modules (help, then init or query when the user
   actually wants those operations). Do not run them.

## Outputs

A fenced `text` card plus a short first-use explanation. No store writes.
No new git remotes. No schema overlay install.

## Side effects and boundaries

**Forbidden during this module:** `atlas mount`, `atlas init`,
`atlas store init`, schema install, `atlas remember`, `atlas search` used as
path **query**, compile, commit, push, index build, `gh repo create`.

Reading this module is not authority to create a store.

## Non-goals

- Implementing or opening **visualise** / Cartograph.
- Adding CLI verbs or catalog skills.
- Preferring a newly created dedicated repository.
