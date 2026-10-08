---
title: ci
description: Assess, install or repair the CI merge gate that compiles an Atlas store on every pull request and push.
sidebar:
  order: 15
source:
  - references/paths/ci.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/ci.md: 5a3c3a2fab52f049929cce14f5878c068dc74bc7
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `ci` module sets up a continuous integration (CI) merge gate for an Atlas store.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
Its root holds one contract file: `SCHEMA.json` or `CONTRACT.json`.
The gate runs the `compile` command on every pull request and push.
*Compile* is the CLI check of store shape, required frontmatter and required links.

## When

Use `ci` when a repository with an Atlas contract file:

- needs a CI merge gate;
- has a CI setup that you want assessed;
- has a compile workflow that is partial or incorrect.

`ci` targets the repository that holds the store (the *mount repository*).
It does not target the Atlas skill package, its Python tests or its release pipeline.

## What it does

Three layers stay distinct:

| Name | Layer | Job |
|------|-------|-----|
| `path: ci` | Agent module | Discover, assess, install or repair, and emit a receipt |
| Platform adapter | GitHub Actions by default | Trigger, get the pinned CLI, run the gate, keep evidence |
| `compile` command | CLI tool | Run the unfocused store gate |

A separate agent-session compile discipline exists. It is not the same as `ci`, which is the institutional merge gate.

The canonical gate (model v1.1) works like this on any CI platform:

- The subject has exactly one contract file. A dedicated store uses the git root. An embedded store declares the contract file's parent folder.
- Root discovery fails closed. A missing file, an ambiguous root, or both files present is not success.
- The gate runs an unfocused compile with `--json`, without `--path` or `--type`:

  ```text
  python3 <atlas-skill>/scripts/atlas.py compile --root <root> --json
  ```

- Exit `0` passes. Exit `1` passes, and the warnings are kept as evidence. Exit `2` fails. Any other abnormal failure fails.
- The CLI comes from an immutable tag or commit SHA, never `main` or `master`. Dependencies install from the exact lock that ships with that CLI. Any acquisition failure fails the job.
- The gate runs on pull requests and on pushes that include the default branch.
- The compile job has read-only permissions on the store.
- The compile JSON is printed in the log and kept as an artifact, even when the gate fails.
- One job compiles one Atlas root.

The agent then follows these steps:

1. **Resolve the mount and root.** It uses the card `root` if that holds exactly one contract file. Otherwise it uses `.` if the git root holds one. Otherwise it searches the mount tree for exactly one contract file. Zero or several candidates fail closed. If the candidate is the Atlas skill package, it stops.
2. **Detect the adapter.** A GitHub remote or a `.github/` folder selects GitHub Actions. An unknown platform is assess-only unless you name an adapter.
3. **Assess.** It checks identity, gate, CLI, triggers, privilege, evidence and anti-patterns. It reports a grade and the failed check IDs.
4. **For `assess`, it stops** after the report and receipt.
5. **For `install` or `repair`,** it prefers a thin caller of the Atlas reusable workflow when cross-repository access is set up. Otherwise it copies the self-contained workflow to `<mount>/.github/workflows/atlas-compile.yml`. It sets the real root and an immutable CLI ref, such as the release tag `v0.13.0-beta.13`.
6. **Re-assess.** The result must be `correct`, or `partial` with every remaining failed ID named.
7. **Emit the receipt.**

Grades:

| Grade | Meaning |
|-------|---------|
| `missing` | No job compiles a contract-file root. |
| `partial` | Compile runs, but a required clause is weak, such as missing evidence, a missing trigger or floating third-party Action tags. |
| `incorrect` | A forbidden pattern is present, the wrong root is targeted, or a critical exit is swallowed. |
| `correct` | Every required clause holds and no forbidden pattern is present. |

Both shipped GitHub Actions adapters get the CLI under `${RUNNER_TEMP}`, not inside the workspace.
They upload the JSON with `if: always()` and pin third-party Actions to commit SHAs.
For a private Atlas skill repository, set `ATLAS_CLI_TOKEN` with read-only contents access. A public source can use `github.token`.

## How to ask for it

Ask the agent to assess, install or repair Atlas CI for your store repository.
"Atlas CI" and "GitHub Actions compile gate" are trigger phrases for Atlas.
The card `intent` is one of `assess`, `install` or `repair`.
To learn about the module without running it, ask "explain ci" or "Atlas help ci".

## Activation card

The agent renders the card as a fenced `text` block:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: <mount repository>
path: ci
path_module: references/paths/ci.md
intent: assess | install | repair
root: <contract file parent>
```

The card and the loaded module are both required. Without them, Enter is incomplete.

The exit receipt records `adapter`, `grade` and `failing_ids`.
It always has `remember: no` and `compile: n/a`, because `ci` writes no knowledge and does not run the store pipeline.

## Boundaries

:::danger
Never point the gate at a floating branch such as `main`.
Use a release tag or a commit SHA for both the CLI and the reusable workflow.
:::

The gate must never:

- use a focused `--path` or `--type` compile as the merge gate;
- succeed when the contract file is missing, or when both files are present;
- substitute Atlas skill unit tests or package publishing for store compile;
- swallow exit `2`, for example with `continue-on-error` on the compile step;
- require secrets other than a read token for a private CLI source;
- become tag-based product release automation;
- get the CLI inside the store tree that it compiles.

Optional extras are allowed: manual or scheduled runs, failing on warnings as a stricter local policy, and extra formatters or linters outside the Atlas gate.

Non-goals: running the store pipeline from this module, the agent-session compile discipline, Atlas skill tests or releases, inventing an adapter for an unnamed platform, and changing compile exit codes.

## Related CLI commands

- [`compile`](/atlas/reference/cli/compile/)
- [`validate`](/atlas/reference/cli/validate/) (an alias of `compile` that the gate may use)

## Related modules

- [`help`](/atlas/modules/help/) explains `ci` without running it.
