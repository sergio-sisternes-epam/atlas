---
title: "atlas.py recall run"
description: "Generated reference for the Atlas CLI command recall run at v0.13.0-beta.13."
sidebar:
  label: "recall run"
  order: 15
source:
  - scripts/atlas_cli/cli.py
source_sha:
  scripts/atlas_cli/cli.py: 088b1595536e93d3622e90476a557c5622930324
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas CLI at `v0.13.0-beta.13`. Do not edit it manually.

Summary from the help text: Discover concepts (tool). Agent protocol is path recall + B17 card.

Run it from the installed skill directory:

```text
python3 <atlas-skill>/scripts/atlas.py recall run ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas.py recall run --help`:

```text
Usage: atlas.py recall run [OPTIONS] QUERY

  Discover concepts (tool). Agent protocol is path recall + B17 card.

Options:
  --root TEXT           Atlas store root (default: cwd)
  --limit INTEGER       max hits  [default: 10]
  --engine [grep|bm25]  override SCHEMA query.search_engine
  --json                machine-readable output
  --include-exits       include kva/status terminated|deprecated|superseded
                        (also via kva:terminated)
  --profile TEXT        request-scoped SCHEMA 2.0 recall profile
  --allow-partial       SCHEMA 2.0: return incomplete corpus results (exit 1)
  -h, --help            Show this message and exit.
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form and exit codes.
