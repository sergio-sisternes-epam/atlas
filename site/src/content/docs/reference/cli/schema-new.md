---
title: "atlas.py schema new"
description: "Generated reference for the Atlas CLI command schema new at v0.13.0-beta.13."
sidebar:
  label: "schema new"
  order: 23
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Start a project-local overlay under schema.d/&lt;id&gt;.json.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py schema new ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py schema new --help`:

```text
Usage: atlas.py schema new [OPTIONS] CID

  Start a project-local overlay under schema.d/<id>.json.

Options:
  --root TEXT   Atlas store root (default: cwd)
  --claim TEXT  claimed folder prefix (repeatable)
  --json        machine-readable output
  -h, --help    Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
