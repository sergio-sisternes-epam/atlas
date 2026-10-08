---
title: "Modules"
description: "Every Atlas module in the installed path registry, with a one-line purpose."
sidebar:
  label: "All modules"
  order: 0
source:
  - SKILL.md
source_sha:
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
source_tag: v0.13.0-beta.13
generated: true
---

This table is generated from the `SKILL.md` path registry at `v0.13.0-beta.13`.

A *module* is one procedure that the agent loads for one intent. The skill calls a module a *path*. Modules are not separate skills. CLI commands are tools that modules use.

| Module | When to use it | Page |
|--------|----------------|------|
| `mount` | Mount-if-missing and resolve `--root` | [mount](/atlas/modules/mount/) |
| `init` | New Atlas; default shared (`atlas` branch) or dedicated existing remote; never creates the repo | [init](/atlas/modules/init/) |
| `migrate` | Relocate `references/atlas`, or rehost shared ↔ dedicated | [migrate](/atlas/modules/migrate/) |
| `memory-migrate` | Assess, inventory, or apply a named batch from a document-era store toward memory | [memory-migrate](/atlas/modules/memory-migrate/) |
| `recall` | Find / answer from an Atlas | [recall](/atlas/modules/recall/) |
| `remember` | Write experiences, decisions, lessons, recipes; compile green | [remember](/atlas/modules/remember/) |
| `atlas-memorise` | Choose the four-layer write target, then load path remember | [atlas-memorise](/atlas/modules/atlas-memorise/) |
| `atlas-recall` | Navigate the four-layer model by loading path recall | [atlas-recall](/atlas/modules/atlas-recall/) |
| `atlas-forget` | Drop memory with keep, vary, or abandon | [atlas-forget](/atlas/modules/atlas-forget/) |
| `atlas-optimise` | Operator-chosen fill and tidy of a named target: evidence-gated gist and schema fill, four-layer tidy repair, subject clustering, per-folder task list, dry-run first; not on install or compile | [atlas-optimise](/atlas/modules/atlas-optimise/) |
| `work` | Open, update, or close `work_id` hubs | [work](/atlas/modules/work/) |
| `landscape` | On-demand competitor + symbiont research; write comparison memory | [landscape](/atlas/modules/landscape/) |
| `schema` | Init, overlay install/new/uninstall; compile merge | [schema](/atlas/modules/schema/) |
| `configure` | SCHEMA 2.0 recall inspect, upgrade, explicit profile selection | [configure](/atlas/modules/configure/) |
| `ci` | Assess, install, or repair CI for a `SCHEMA.json` mount | [ci](/atlas/modules/ci/) |
| `help` | Explain installed modules without running them | [help](/atlas/modules/help/) |
| `getting-started` | First-use purpose, prerequisites, first journey, storage choices | [getting-started](/atlas/modules/getting-started/) |

To learn about a module in a session, ask the agent, for example `/atlas help recall`. The agent explains the module from the installed skill and does not run it.
