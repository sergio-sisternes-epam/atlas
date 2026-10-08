---
title: "atlas.py auth"
description: "Generated reference for the Atlas CLI command auth at v0.13.0-beta.13."
sidebar:
  label: "auth"
  order: 1
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: login | list | logout | status. Records host/backend only, never a PAT.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py auth ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py auth --help`:

```text
Usage: atlas.py auth [OPTIONS] [ACTION]

  login | list | logout | status. Records host/backend only, never a PAT.

Options:
  --host TEXT  [default: github.com]
  --org TEXT   optional org override grain
  --ssh
  --json
  -h, --help   Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
