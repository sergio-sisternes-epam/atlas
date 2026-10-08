---
title: "atlas.py compile"
description: "Generated reference for the Atlas CLI command compile at v0.13.0-beta.13."
sidebar:
  label: "compile"
  order: 2
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Alias for validate (compile success = validate green + staging empty).

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py compile ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py compile --help`:

```text
Usage: atlas.py compile [OPTIONS]

  Alias for validate (compile success = validate green + staging empty).

Options:
  --root TEXT  Atlas store root (default: cwd)
  --json       machine-readable output
  --type TEXT  focus page walk on this frontmatter type
  --path TEXT  focus page walk on this store-relative prefix
  --dry-run    report findings only; never write mesh.json or publish the
               recall index
  -h, --help   Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
