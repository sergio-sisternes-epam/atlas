---
title: "atlas.py store rehost"
description: "Generated reference for the Atlas CLI command store rehost at v0.13.0-beta.13."
sidebar:
  label: "store rehost"
  order: 28
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Move store history between shared and dedicated. Does not import pages.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py store rehost ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py store rehost --help`:

```text
Usage: atlas.py store rehost [OPTIONS]

  Move store history between shared and dedicated. Does not import pages.

Options:
  --destination-strategy [shared|dedicated]
                                  [required]
  --remote TEXT                   existing dedicated remote (required when
                                  destination is dedicated)
  --id TEXT                       source store id (default: sole mesh row)
  --ssh
  --cwd TEXT
  --json
  -h, --help                      Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
