---
title: "atlas.py schema"
description: "Generated reference for the Atlas CLI command group schema at v0.13.0-beta.13."
sidebar:
  label: "schema"
  order: 20
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Create, install, or uninstall SCHEMA overlays (CLI is the only writer).

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py schema ...
```

## Subcommands

- [`schema install`](/atlas/reference/cli/schema-install/)
- [`schema memory-rung`](/atlas/reference/cli/schema-memory-rung/)
- [`schema new`](/atlas/reference/cli/schema-new/)
- [`schema uninstall`](/atlas/reference/cli/schema-uninstall/)
- [`schema upgrade`](/atlas/reference/cli/schema-upgrade/)

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py schema --help`:

```text
Usage: atlas.py schema [OPTIONS] COMMAND [ARGS]...

  Create, install, or uninstall SCHEMA overlays (CLI is the only writer).

Options:
  -h, --help  Show this message and exit.

Commands:
  install      Copy a skill or file overlay into schema.d/.
  memory-rung  Write SCHEMA.memory.rung (the only writer of that block).
  new          Start a project-local overlay under schema.d/<id>.json.
  uninstall    Remove an overlay and receipt-listed CLI writes.
  upgrade      Upgrade SCHEMA 1.0 to 2.0.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
