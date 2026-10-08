---
title: "atlas.py recall"
description: "Generated reference for the Atlas CLI command group recall at v0.13.0-beta.13."
sidebar:
  label: "recall"
  order: 9
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Discover (recall run), inspect, validate, activate, or index SCHEMA 2.0 recall.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py recall ...
```

## Subcommands

- [`recall activate`](/atlas/reference/cli/recall-activate/)
- [`recall disable`](/atlas/reference/cli/recall-disable/)
- [`recall index`](/atlas/reference/cli/recall-index/)
- [`recall profiles`](/atlas/reference/cli/recall-profiles/)
- [`recall run`](/atlas/reference/cli/recall-run/)
- [`recall show`](/atlas/reference/cli/recall-show/)
- [`recall status`](/atlas/reference/cli/recall-status/)
- [`recall validate`](/atlas/reference/cli/recall-validate/)

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py recall --help`:

```text
Usage: atlas.py recall [OPTIONS] COMMAND [ARGS]...

  Discover (recall run), inspect, validate, activate, or index SCHEMA 2.0
  recall.

Options:
  -h, --help  Show this message and exit.

Commands:
  activate
  disable
  index     Recall index generations.
  profiles
  run       Discover concepts (tool).
  show
  status
  validate
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
