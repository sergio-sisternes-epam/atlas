---
title: "atlas.py schema memory-rung"
description: "Generated reference for the Atlas CLI command schema memory-rung at v0.13.0-beta.13."
sidebar:
  label: "schema memory-rung"
  order: 22
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Write SCHEMA.memory.rung (the only writer of that block).

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py schema memory-rung ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py schema memory-rung --help`:

```text
Usage: atlas.py schema memory-rung [OPTIONS]

  Write SCHEMA.memory.rung (the only writer of that block).

Options:
  --set [info|warn|error]  memory.rung severity for legacy_document/missing_gi
                           st/gist_parent/frame_members  [required]
  --root TEXT              Atlas store root (default: cwd)
  --json                   machine-readable output
  -h, --help               Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
