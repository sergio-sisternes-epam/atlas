---
title: CLI reference
description: How to run the Atlas CLI, its global options, exit codes and the --json convention.
sidebar:
  label: Overview
  order: 0
source:
  - SKILL.md
  - scripts/atlas_cli/cli.py
  - scripts/atlas.py
source_sha:
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
  scripts/atlas.py: 9b620288edaafa53e0aa3462fc04cd88dc10830b
source_tag: v0.13.0-beta.13
---

Atlas ships a deterministic Python command-line interface (CLI).
Modules call the CLI as a tool.
You can also run it yourself.
The pages in this section mirror the CLI at release `v0.13.0-beta.13`.

## Invocation form

Run the CLI from the installed skill directory.
`<atlas-skill>` is the installed skill path (the `skill_path` on the activation card).
Do not resolve the commands relative to your project.

```text
python3 <atlas-skill>/scripts/atlas.py <command> [<subcommand>] [OPTIONS]
```

`scripts/atlas.py` is a small shim.
All logic lives in the `atlas_cli` package.

The optimise helper is a separate script:

```text
python3 <atlas-skill>/scripts/atlas_optimise.py plan|apply ...
```

Only the [`atlas-optimise`](/atlas/modules/atlas-optimise/) module uses it.
See [`atlas_optimise.py`](/atlas/reference/cli/atlas-optimise-script/).

## Global options

| Option | What it does |
| --- | --- |
| `--version` | Prints the version and exits. |
| `-h`, `--help` | Prints help and exits. Every command and subcommand accepts it. |

`--help` never changes anything.
Option lists come from the installed `--help`, not from memory.

## Exit codes

The root help ends with this line:

```text
Exit: 0 ok/non-blocking dependency warnings · 1 actionable warnings · 2 critical
```

| Code | Meaning |
| --- | --- |
| `0` | OK. There may be non-blocking dependency warnings. |
| `1` | Actionable warnings. |
| `2` | Critical. |

A write to a store ends when [`compile`](/atlas/reference/cli/compile/) exits with code 0.
This is a *green* compile.

## The `--json` convention

Every command takes a `--json` flag.
With `--json`, the command prints machine-readable output instead of text.
Agents use `--json` when they need to parse the result.
For example, the [`init`](/atlas/modules/init/) module runs:

```text
python3 <atlas-skill>/scripts/atlas.py store init --strategy shared --json
```

## Common shape

Most commands that work on a store take `--root <atlas>`.
`<atlas>` is the store root that the [`mount`](/atlas/modules/mount/) module resolves.

```text
python3 <atlas-skill>/scripts/atlas.py compile --root <atlas>
python3 <atlas-skill>/scripts/atlas.py recall run "..." --root <atlas>
```

## Commands

Each page shows a short lead and the exact `--help` output.
The pages are generated, so they always match the release.

| Command | Help page |
| --- | --- |
| `auth` | [auth](/atlas/reference/cli/auth/) |
| `compile` | [compile](/atlas/reference/cli/compile/) |
| `id` | [id](/atlas/reference/cli/id/) |
| `init` | [init](/atlas/reference/cli/init/) |
| `memory-migrate` | [memory-migrate](/atlas/reference/cli/memory-migrate/) |
| `migrate` | [migrate](/atlas/reference/cli/migrate/) |
| `mount` | [mount](/atlas/reference/cli/mount/) |
| `promote` | [promote](/atlas/reference/cli/promote/) |
| `recall` | [recall](/atlas/reference/cli/recall/) (group) |
| `resolve` | [resolve](/atlas/reference/cli/resolve/) |
| `schema` | [schema](/atlas/reference/cli/schema/) (group) |
| `store` | [store](/atlas/reference/cli/store/) (group) |
| `validate` | [validate](/atlas/reference/cli/validate/) |

The group pages list their subcommands.
