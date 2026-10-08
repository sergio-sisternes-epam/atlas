---
title: Install
description: Install Atlas from the marketplace or from a pinned release tag with the APM CLI, then install the Python dependencies of the Atlas CLI.
source:
  - README.md
  - references/help/getting-started.md
  - CONTRIBUTING.md
  - scripts/requirements.txt
source_sha:
  README.md: 504c2d65ab2b42dabe8a456d0ce08d9ca85f3de7
  references/help/getting-started.md: b1c704e59354a1bacd0e4b98c53dbde67b3e3d0c
  CONTRIBUTING.md: 4b82aac94ff862293369545c8a0fe1a44e1dbd3e
  scripts/requirements.txt: 2007fd44bc2bf1c040b80dd2b432bcb5bf02a53e
source_tag: v0.13.0-beta.13
---

You install Atlas as a skill package with the APM CLI.
Use the marketplace, or pin an exact release tag.
Then you install the Python dependencies of the Atlas CLI.

## Prerequisites

- APM CLI 0.30.0 or newer.
- Python 3.10 or newer.
- The Python dependencies from `<atlas-skill>/scripts/requirements.txt` (see below).
- A git repository in your session before you use the `init`, `mount` or `remember` modules.
  You do not need a store to read help or the getting-started article.

`<atlas-skill>` means the directory where the Atlas skill is installed.

If you install from public GitHub, you do not need a personal access token.
This applies to Atlas and to its separate `okf` dependency.

## Install from the marketplace

Consumer install is marketplace-only:

```bash
apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas
apm install atlas@atlas
```

The `--name atlas` option is required.
It makes the package resolve as `atlas@atlas`.

## Install a pinned release tag

To install one exact release, pin its tag, for example `#v0.13.0-beta.13`:

```bash
apm install sergio-sisternes-epam/atlas#v0.13.0-beta.13
```

APM version ranges skip prerelease tags.
A beta release such as `v0.13.0-beta.13` can only be installed by pinning that exact tag.

:::danger
Never install Atlas from a branch. Use the marketplace or an exact release tag.
:::

## Install the Python dependencies

Install the CLI dependencies in the Python environment that will run Atlas:

```text
python3 -m pip install -r <atlas-skill>/scripts/requirements.txt
```

At `v0.13.0-beta.13`, the file lists:

```text
jsonschema>=4.18
click>=8.0
PyYAML>=6.0
```

## Option lists

The installed CLI is the reference for options.
Read them with the non-mutating `--help` of a command, for example:

```text
python3 <atlas-skill>/scripts/atlas.py --help
```

The [CLI reference](/atlas/reference/cli/) mirrors that output at this release.

## Next steps

- Ask in an agent session: `/atlas How can I get started?`
- Walk the [first journey](/atlas/start/first-journey/).
