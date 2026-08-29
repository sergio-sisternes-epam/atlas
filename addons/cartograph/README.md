# Cartograph (Atlas, Build only)

Fork of `okf-wiki/addons/graph-viewer`. See `FORK.md`.

**This directory is the only Cartograph / Atlas viewer source.** The Build host
imports it. Do not copy these files into the app.

This UI is **Grok Build only**. The skill does not ship a standalone server.

Other sessions: use `python3 scripts/atlas.py search|validate`. No Vite, no view host.

## Store root — skill stores by default, env to override

Defaults (relative to this skill, not host copies):

- `.atlas/github.com/sergio-sisternes-epam/atlas-atlas/atlas` — skill process memory (after mount)
- `fixtures/mini-atlas` — fixture

Absolute paths are **not** committed for third-party stores. Inject those at host startup:

```bash
export ATLAS_ROOT=/absolute/path/to/atlas
export ATLAS_PRESETS="Project:/path/to/project-atlas"
npm run dev
```

Or one-shot:

```bash
python3 scripts/atlas.py view --root /absolute/path/to/atlas --check
# → http://127.0.0.1:8080/?root=/absolute/path/to/atlas
```

Priority: `?root=` → UI field → `ATLAS_ROOT` / `ATLAS_VIEWER_ROOT` → skill stores.

Any folder with `SCHEMA.json` or `index.md` is an Atlas. Legacy okf-wiki stores (`knowledge/`, `SCHEMA.md`) still open.

## Contract (Build host)

- Import only — never duplicate this tree
- Live-read a store **root** at runtime
- No graph export file
- Host mounts `CartographApp`

```ts
import { CartographApp } from "@atlas/cartograph";
```
