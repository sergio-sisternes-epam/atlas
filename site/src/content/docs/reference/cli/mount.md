---
title: "atlas.py mount"
description: "Generated reference for the Atlas CLI command mount at v0.13.0-beta.13."
sidebar:
  label: "mount"
  order: 7
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Mount a git-backed Atlas in-repo; default: .atlas/&lt;id&gt;/.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py mount ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py mount --help`:

```text
Usage: atlas.py mount [OPTIONS] SOURCE

  Mount a git-backed Atlas in-repo; default: .atlas/<id>/.

Options:
  --ref TEXT     branch or tag to check out
  --target TEXT  override mount path
  --ssh          use SSH remote
  --cwd TEXT     project directory
  --json
  -h, --help     Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
