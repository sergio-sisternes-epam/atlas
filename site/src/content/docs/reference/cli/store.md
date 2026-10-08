---
title: "atlas.py store"
description: "Generated reference for the Atlas CLI command group store at v0.13.0-beta.13."
sidebar:
  label: "store"
  order: 26
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Shared (consumer atlas branch) or dedicated (separate repo) storage.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py store ...
```

## Subcommands

- [`store init`](/atlas/reference/cli/store-init/)
- [`store rehost`](/atlas/reference/cli/store-rehost/)

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py store --help`:

```text
Usage: atlas.py store [OPTIONS] COMMAND [ARGS]...

  Shared (consumer atlas branch) or dedicated (separate repo) storage.

Options:
  -h, --help  Show this message and exit.

Commands:
  init    Bootstrap a store.
  rehost  Move store history between shared and dedicated.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
