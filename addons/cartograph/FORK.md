# Cartograph — Atlas fork of okf-wiki graph-viewer

**Upstream:** `okf-wiki/addons/graph-viewer` (Grok Build sky).

**This fork** lives in `atlas/addons/cartograph/`. It is not a submodule and
does not track okf-wiki. Changes here do not flow back.

## Why fork

okf-wiki assumed `knowledge/` · `raw/` · `modules/` and `SCHEMA.md`.
Atlas is free-layout OKF v0.2 with `SCHEMA.json`, `relates_to`, and `atlas://`.

## Delta vs upstream

| | okf-wiki graph-viewer | Atlas Cartograph |
|---|---|---|
| Store detect | `knowledge/`, `SCHEMA.md`, `index.md` | `SCHEMA.json` or `index.md` (wiki still accepted) |
| Layout | Fixed folders | Free layout; skip `staging/`, `templates/`, `mesh/` |
| Node kinds | knowledge / raw / module / index | experience / decision / work / lesson / recipe / index / page |
| Authoritative edges | wikilinks + `sources:` | frontmatter `relates_to: [{path, kind}]` |
| Mesh | — | `atlas://<atlas-id>/<path>` |
| CLI | `okf_wiki.py view` | `atlas view` |
| Import | `@okf-wiki/graph-viewer` | `@atlas/cartograph` |

Do not load `okf-wiki` graph-viewer when the store is an Atlas.
