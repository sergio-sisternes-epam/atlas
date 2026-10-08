---
title: "atlas.py store init"
description: "Generated reference for the Atlas CLI command store init at v0.13.0-beta.13."
sidebar:
  label: "store init"
  order: 27
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Bootstrap a store. Default strategy is shared. Never creates a host repo.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py store init ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py store init --help`:

```text
Usage: atlas.py store init [OPTIONS]

  Bootstrap a store. Default strategy is shared. Never creates a host repo.

Options:
  --strategy [shared|dedicated]  [default: shared]
  --remote TEXT                  git URL; shared defaults to consumer origin
  --ssh
  --cwd TEXT                     project directory
  --json
  --schema-version TEXT          [default: 1.0]
  -h, --help                     Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
