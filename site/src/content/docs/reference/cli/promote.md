---
title: "atlas.py promote"
description: "Generated reference for the Atlas CLI command promote at v0.13.0-beta.13."
sidebar:
  label: "promote"
  order: 8
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Scaffold staging file into durable page; agent finishes claims/links.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py promote ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py promote --help`:

```text
Usage: atlas.py promote [OPTIONS] STAGING_FILE

  Scaffold staging file into durable page; agent finishes claims/links.

Options:
  --to TEXT    target path relative to atlas root, e.g. decisions/foo.md
               [required]
  --root TEXT  Atlas store root (default: cwd)
  --type TEXT  template type hint, e.g. experience | decision
  --json       machine-readable output
  -h, --help   Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
