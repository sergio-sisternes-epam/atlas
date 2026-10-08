---
title: "atlas.py schema install"
description: "Generated reference for the Atlas CLI command schema install at v0.13.0-beta.13."
sidebar:
  label: "schema install"
  order: 21
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Copy a skill or file overlay into schema.d/.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py schema install ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py schema install --help`:

```text
Usage: atlas.py schema install [OPTIONS] SOURCE

  Copy a skill or file overlay into schema.d/.

Options:
  --root TEXT  Atlas store root (default: cwd)
  --force      overwrite existing overlay (required if required-keys changed)
  --json       machine-readable output
  -h, --help   Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
