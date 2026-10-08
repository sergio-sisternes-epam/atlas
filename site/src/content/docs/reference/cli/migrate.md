---
title: "atlas.py migrate"
description: "Generated reference for the Atlas CLI command migrate at v0.13.0-beta.13."
sidebar:
  label: "migrate"
  order: 6
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Copy external/old content into staging/ only (no compile).

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py migrate ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py migrate --help`:

```text
Usage: atlas.py migrate [OPTIONS] SOURCE

  Copy external/old content into staging/ only (no compile).

Options:
  --root TEXT  Atlas store root (default: cwd)
  --into TEXT  staging directory name (default from SCHEMA or 'staging')
  --json       machine-readable output
  -h, --help   Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
