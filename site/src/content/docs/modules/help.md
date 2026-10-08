---
title: help
description: Explain installed Atlas modules without running them, from the bundled baseline first.
sidebar:
  order: 16
source:
  - references/paths/help.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/help.md: 2a0d76951e9448a77f5ee3b697f4632e030ee6ea
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `help` module explains Atlas modules without running them.
It is a read-only *discussion* module.
It answers from the *bundled baseline*: help files that ship inside the installed Atlas skill.
It works with no store mounted.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.

## When

Use `help` when you want to know what Atlas can do, to list its modules, or to understand one module or topic without performing it.
Unqualified "help" outside an Atlas context does not enter this module.

## What it does

1. **Dispatch.**
   - No target: the agent lists every module in the installed registry, with a one-line purpose. It does not ask you to clarify first.
   - A named module or topic: the agent explains that topic only.
   - An unknown name: the agent says it is unknown and lists the valid choices. It does not invent modules or flags.
2. **Baseline first.** The agent reads packaged files before any store.
   - For a list or an unknown name, it reads the help catalog.
   - For a named module, it reads only that module's own file.
   - For first-use questions, it reads the bundled getting-started article.
   - For CLI options, it runs the matching non-mutating `--help`, for example:

     ```text
     python3 <atlas-skill>/scripts/atlas.py recall run --help
     python3 <atlas-skill>/scripts/atlas.py mount --help
     ```

   If the baseline answers the real question, the agent stops there.
   Topic overlap or fluent general knowledge is not enough. A partial answer is a gap.
3. **Optional enrichment, for gaps only.**
   - The agent may run `resolve` on a store that is already registered. It never mounts a missing store.
   - It uses the resolved path only if the path is inside the active git repository and holds a valid `SCHEMA.json`.
   - It then searches with the read-only grep engine only. It passes no `--profile`, builds no index and does not enable recall.

     ```text
     python3 <atlas-skill>/scripts/atlas.py resolve <atlas_id>
     python3 <atlas-skill>/scripts/atlas.py recall run "<question>" --root <root> --json --engine grep
     ```

   - It reads 1 to 3 pages, with at most one justified rewrite, and never reads `staging/`.
   - If any step fails, it does not fall back to model knowledge. It marks the help as limited and names the reason.
4. **Explain a named module.** The agent covers intent, inputs, prerequisites, examples, outputs, side effects and boundaries.

This search is not the [`recall`](/atlas/modules/recall/) module. It is a read-only tool under the help card.

## How to ask for it

- "Atlas help", "what can Atlas do?" or "list modules" lists every installed module.
- `Atlas help <module>` or `explain <module>` explains one module, for example "explain atlas mount".
- "List atlas paths" and "how does atlas work" are also trigger phrases for Atlas.

## Activation card

The agent emits this card without emitting `mount` first:

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

The card and the loaded module are both required.
`path` stays `help` even when the topic is `mount`, `init`, `remember` or `recall`.
`intent` names understanding, for example "Understand how mount works without mounting a store".

The card fields mean:

- `atlas_id` and `root`: the selected store, not proof that it was used. Only a read-only `resolve` may set a real `root`.
- `atlas_status`: `not-queried`, `baseline-only`, `consulted` or `unavailable`. `unavailable` adds a short `atlas_reason`.
- `atlas_used`: only stores whose evidence contributed to the answer.
- `help_status`: `complete` or `limited` at the end.

After any retrieval, the agent refreshes the card before the explanation.
The final card has no `pending` values. A baseline-only answer sets `atlas_status: baseline-only`, `atlas_used: []` and `help_status: complete`.
The exit receipt always has `remember: no` and `compile: n/a`. The card and the prose must agree.

## Boundaries

:::note
Help explains. It does not execute.
:::

- The agent must not mount, init, schema-install, remember, compile, commit, push or build an index to explain a module.
- It does not mount a missing store, authenticate, repair or install anything to get past a failure.
- It rejects resolved paths outside the active repository, including `../` mesh paths and symlink escapes.
- It ignores any search hint that says to enter the `recall` module.
- Historical or unapproved proposals are not current installed capability.
- Non-goals: new catalog skills, a help CLI verb, auto-mount, schema overlay install, a public wiki, and a "visualise" feature.

## Related CLI commands

- [`resolve`](/atlas/reference/cli/resolve/) (read-only, gaps only)
- [`recall run`](/atlas/reference/cli/recall-run/) (with `--engine grep` only, gaps only)

## Related modules

- [`getting-started`](/atlas/modules/getting-started/) covers first use.
- [`mount`](/atlas/modules/mount/), [`init`](/atlas/modules/init/), [`remember`](/atlas/modules/remember/), [`recall`](/atlas/modules/recall/), [`schema`](/atlas/modules/schema/), [`configure`](/atlas/modules/configure/), [`ci`](/atlas/modules/ci/), [`migrate`](/atlas/modules/migrate/) and [`work`](/atlas/modules/work/) are modules that `help` explains but never runs.
