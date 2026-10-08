---
title: "atlas.py memory-migrate"
description: "Generated reference for the Atlas CLI command memory-migrate at v0.13.0-beta.13."
sidebar:
  label: "memory-migrate"
  order: 5
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Pre-beta -&gt; 0.13.0-beta.7 contract-file migration (path memory-migrate).

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py memory-migrate ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py memory-migrate --help`:

```text
Usage: atlas.py memory-migrate [OPTIONS]

  Pre-beta -> 0.13.0-beta.7 contract-file migration (path memory-migrate).

Options:
  --root TEXT                     Atlas store root (default: cwd)
  --operation [assess|inventory|apply]
                                  assess/inventory write nothing; apply
                                  rewrites a pre-beta contract or an empty
                                  unstamped full beta.2 init  [required]
  --batch TEXT                    explicit batch token for apply (only
                                  'contract-file' is implemented)
  --json                          machine-readable output
  -h, --help                      Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
