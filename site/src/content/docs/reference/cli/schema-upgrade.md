---
title: "atlas.py schema upgrade"
description: "Generated reference for the Atlas CLI command schema upgrade at v0.13.0-beta.13."
sidebar:
  label: "schema upgrade"
  order: 25
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Upgrade SCHEMA 1.0 to 2.0. Does not enable recall.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py schema upgrade ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py schema upgrade --help`:

```text
Usage: atlas.py schema upgrade [OPTIONS]

  Upgrade SCHEMA 1.0 to 2.0. Does not enable recall.

Options:
  --root TEXT          Atlas store root (default: cwd)
  --to TEXT            [default: 2.0]
  --apply / --dry-run  write SCHEMA 2.0 and compatibility overlay / preview
                       (default)
  --json
  -h, --help           Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
