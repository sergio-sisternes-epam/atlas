---
name: atlas/help/baseline
description: Versioned bundled Atlas module catalog. Help lists from this file plus the SKILL.md path registry; no Atlas mount required.
package_version: 0.11.2
---

# Bundled help baseline

This directory is the **versioned packaged baseline** for Atlas modules
`help` and `getting-started`. It ships with this skill at
`package_version` **0.11.2** (see `VERSION`). Help works with **no Atlas
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
| **query** | Find / answer from an Atlas |
| **remember** | Write experiences, decisions, lessons, recipes; compile green |
| **work** | Open, update, or close `work_id` hubs |
| **landscape** | On-demand competitor + symbiont research; write comparison memory |
| **schema** | Init, overlay install/new/uninstall; compile merge |
| **configure** | SCHEMA 2.0 recall inspect, upgrade, explicit profile selection |
| **ci** | Assess, install, or repair CI for a `SCHEMA.json` mount |

Named-module details live in `references/paths/<module>.md` in this same
package revision. CLI option lists come from that revision’s non-mutating
`python3 <atlas-skill>/scripts/atlas.py <verb> --help`, not from memory.
