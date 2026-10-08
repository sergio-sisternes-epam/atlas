---
title: getting-started
description: First-use guidance that explains what Atlas does, what you need, a first journey and where knowledge can live, without creating a store.
sidebar:
  order: 17
source:
  - references/paths/getting-started.md
  - SKILL.md
  - references/help/index.md
  - references/help/getting-started.md
source_sha:
  references/paths/getting-started.md: 2235080654856442fc54daeb7c7a095732d1f548
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
  references/help/getting-started.md: b1c704e59354a1bacd0e4b98c53dbde67b3e3d0c
source_tag: v0.13.0-beta.13
---

The `getting-started` module gives first-use guidance for Atlas.
It is a read-only *discussion* module, like [`help`](/atlas/modules/help/).
It answers from a bundled first-use article that ships inside the installed Atlas skill.
It never creates a *store*, which is a git repository (or branch) that holds Atlas knowledge pages.

## When

Use `getting-started` when you are new to Atlas, when you ask how it works or how to start, or when you ask where knowledge can live.
The agent explains. It does not run `init`, `mount`, `recall` or `remember`.

## What it does

1. **Load the bundled baseline.** The agent reads the packaged first-use article and the help catalog. It does not mount, init or search a store.
2. **Answer from the baseline** when it covers your question. The baseline covers:
   - **Purpose.** Atlas keeps knowledge in an OKF store. You pick one module per intent and follow it. The CLI runs from the installed skill directory.
   - **Prerequisites.** APM CLI 0.30.0 or newer, Python 3.10 or newer, the Python dependencies from `<atlas-skill>/scripts/requirements.txt`, and a git repository before `init`, `mount` or `remember`.
   - **Install.** Marketplace only:

     ```bash
     apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas
     apm install atlas@atlas
     python3 -m pip install -r <atlas-skill>/scripts/requirements.txt
     ```

     To install one exact release instead, such as a beta, pin its tag. See [Install a pinned release tag](/atlas/start/install/#install-a-pinned-release-tag).

   - **Shortest first journey.** Install. Ask for getting-started, then help with no target. Ask for help on `mount`, `recall` or `init` before you run them. Run `init` only when you mean to create a store. Then use `recall` to find knowledge and `remember` to write it. Writes end when `compile` exits 0.
   - **Storage choices**, which are equals:

     | Choice | What it is |
     |--------|------------|
     | Existing-repo branch (*shared*) | Knowledge lives on an isolated branch `atlas` of your project repository. It mounts at `.atlas/<id>/`. |
     | Dedicated existing repo | Knowledge lives in a separate repository that already exists. |

     Neither choice creates a new host repository.
     If a dedicated remote does not exist, you create it yourself, then retry.
3. **Check sufficiency.** Topic overlap is not enough. If your question goes beyond the baseline, such as rationale, history or a named module's side effects, the agent follows the [`help`](/atlas/modules/help/) rules for the rest. It uses the same read-only retrieval and the same card fields. It does not run the module it explains.
4. **Refresh the card.** If the baseline answered and nothing was retrieved, the card shows `atlas_status: baseline-only`, `atlas_used: []` and `help_status: complete`, with `atlas_id` and `root` set to `none`. The final card has no `pending` values.
5. **Stop.** The agent suggests next modules: `help`, then `init` or `recall` when you actually want those operations. It does not run them.

The output is a fenced `text` card and a short first-use explanation.
There are no store writes, no new git remotes and no schema overlay installs.

## How to ask for it

Ask "getting started with atlas" or "how does atlas work".
You can also ask how to start with Atlas, or where Atlas knowledge can live.

## Activation card

The agent emits this card without emitting `mount` first:

```text
skill: atlas
skill_path: <atlas skill root>
mode: discussion
subject: atlas
path: getting-started
path_module: references/paths/getting-started.md
intent: Learn what Atlas does and choose a first useful step
atlas_id: <selected store id, pending, or none>
root: <resolved selected store root, pending, or none>
atlas_status: not-queried
atlas_used: []
help_status: pending
```

The card and the loaded module are both required.
`path` stays `getting-started`. The agent never labels this card as `init` or `mount`.
`atlas_id` and `root` name the selected store for possible enrichment. They are not proof that a store was used.

## Boundaries

:::danger
Reading this module is not authority to create a store.
:::

- During this module the agent must not mount, init, initialise a store, install a schema overlay, remember, compile, commit, push or build an index.
- It must not use `recall run` as the [`recall`](/atlas/modules/recall/) module.
- It must not create a GitHub repository.
- It never prefers a newly created dedicated repository.
- Non-goals: a "visualise" feature, new CLI verbs and new catalog skills.

## Related CLI commands

None directly. The module explains commands but runs none of them.
If the baseline cannot answer, the [`help`](/atlas/modules/help/) enrichment rules apply.

## Related modules

- [`help`](/atlas/modules/help/) explains named modules and lists the registry.
- [`init`](/atlas/modules/init/) creates a store when you decide to.
- [`mount`](/atlas/modules/mount/) mounts an existing store.
- [`recall`](/atlas/modules/recall/) and [`remember`](/atlas/modules/remember/) find and write knowledge after a store root exists.
- [`migrate`](/atlas/modules/migrate/) moves history between shared and dedicated storage later.

See also [Install](/atlas/start/install/), [First journey](/atlas/start/first-journey/) and [Choose storage](/atlas/start/choose-storage/).
