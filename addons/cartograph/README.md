# Cartograph (Atlas, Build only)

Fork of `okf-wiki/addons/graph-viewer`. See `FORK.md`.

**This directory is the only Cartograph / Atlas viewer source.** The Build host
imports it. Do not copy these files into the app.

This UI is **Grok Build only**. The skill does not ship a standalone server.

Other sessions: use `python3 scripts/atlas.py search|validate`. No Vite, no view host.

## Store root — inject the mounted store; viewer does not auto-pick it

Canonical skill process memory (after `atlas mount github.com/sergio-sisternes-epam/atlas-atlas --ref main --target references/atlas`):

`references/atlas/atlas`

Cartograph bundled presets look for skill-relative `references/atlas`. The OKF root is nested at `references/atlas/atlas` (`SCHEMA.json` is not at the submodule root). Set `ATLAS_ROOT` / `?root=` to that nested path.

Absolute paths are **not** committed for third-party stores. Inject the mount at host startup:

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
