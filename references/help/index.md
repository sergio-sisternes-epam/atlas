---
name: atlas/help/baseline
description: Versioned bundled Atlas module catalog. Help lists from this file plus the SKILL.md path registry; no Atlas mount required.
package_version: 0.13.0-beta.13
---

# Bundled help baseline

This directory is the **versioned packaged baseline** for Atlas modules
`help` and `getting-started`. It ships with this skill at
`package_version` **0.13.0-beta.13** (see `VERSION`). Help works with **no Atlas
mounted**. If this baseline answers the question, stop; do not query a store.

The installed registry in `SKILL.md` is authoritative for names. This catalog
mirrors that registry so a no-target list does not need every path file.

Ask for details with “explain \<module\>” or “Atlas help \<module\>”.

| module | purpose |
|--------|---------|
| **getting-started** | First-use: purpose, prerequisites, shortest useful journey, storage choices |
| **help** | Explain installed modules without running them |
| **mount** | Mount-if-missing and resolve `--root` |
| **init** | New Atlas; shared (`atlas` branch) or dedicated existing remote; never creates the repo |
| **migrate** | Relocate `references/atlas`, or rehost shared ↔ dedicated |
| **memory-migrate** | Assess or migrate a document-era store toward the memory layers: `memory`/`gist` plus `frame` (shipped-beta) or `schema` (beta.3 `CONTRACT.json`). Assess and inventory write nothing. |
| **recall** | Find / answer from an Atlas |
| **remember** | Write experiences, decisions, lessons, recipes; compile green |
| **atlas-memorise** | Choose layers before a write, then follow remember |
| **atlas-recall** | Navigate by loading path recall; do not restate the walk |
| **atlas-forget** | Keep, vary, or abandon a memory without a new traffic value |
| **atlas-optimise** | Operator-chosen fill and tidy of a named target: evidence-gated gist and schema fill, four-layer tidy repair, subject clustering, per-folder task list, dry-run first; not on install or compile |
| **work** | Open, update, or close `work_id` hubs |
| **landscape** | On-demand competitor + symbiont research; write comparison memory |
| **schema** | Init, overlay install/new/uninstall; compile merge |
| **configure** | SCHEMA 2.0 recall inspect, upgrade, explicit profile selection |
| **ci** | Assess, install, or repair CI for an Atlas mount (reads `SCHEMA.json` or `CONTRACT.json`; new `atlas init` writes `CONTRACT.json`) |
| **history** | Read one store path at a git rev; a relates_to.ref edge is not a tip hop |
| **version-hint** | Add one living-page relates_to.ref hint; grain stays deferred |
| **prune** | After KVA terminate, drop named failed-path pages from tip onto one summary |

Named-module details live in `references/paths/<module>.md` in this same
package revision. CLI option lists come from that revision’s non-mutating
`python3 <atlas-skill>/scripts/atlas.py <verb> --help`, not from memory.
