---
title: "atlas.py init"
description: "Generated reference for the Atlas CLI command init at v0.13.0-beta.13."
sidebar:
  label: "init"
  order: 4
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Write a first CONTRACT.json and default templates.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py init ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py init --help`:

```text
Usage: atlas.py init [OPTIONS]

  Write a first CONTRACT.json and default templates.

Options:
  --root TEXT            Atlas store root (default: cwd)
  --force                overwrite existing CONTRACT.json (and remove a stale
                         SCHEMA.json after the new file is written)
  --json                 machine-readable output
  --schema-version TEXT  SCHEMA envelope version (1.0 stays current behaviour;
                         2.0 adds disabled recall)  [default: 1.0]
  -h, --help             Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
