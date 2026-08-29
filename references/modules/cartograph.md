---
name: cartograph
description: Optional live star-map viewer for an Atlas. Fork of okf-wiki graph-viewer. Trigger on visualise atlas, live graph, show the graph, cartograph, knowledge graph. Only available in Grok Build.
---

# Cartograph (Build only)

**Mode:** the sky runs in **Grok Build**. It is not a portable server.

If this session is **not** Build: say so, do not invent a host, and keep using the CLI (`search`, `validate`). Offer to open Cartograph when they are in Build.

If this session **is** Build:

**Do not hardcode store paths in skill source.** Inject at startup or per view:

```bash
export ATLAS_ROOT=/absolute/path/to/atlas
export ATLAS_PRESETS="Skill memory:/absolute/path/to/references/atlas"

python3 scripts/atlas.py view --root /absolute/path/to/atlas --check
python3 scripts/atlas.py view --root references/atlas --check
```

`view --root` puts `/?root=...` on the preview URL. Never assume skill-memory in code. Any folder with `SCHEMA.json` or `index.md` is an Atlas.

## Layers

- Experiences
- Decisions
- Work
- Indexes
- Relates (`relates_to` / `atlas://`)
- Provenance (`sources:`)

## Fork

`addons/cartograph/FORK.md` — Atlas-native delta vs okf-wiki graph-viewer.

## Strip

`addons/cartograph/STRIP.md` — deleting the add-on must not break compile, search, or the CLI.
