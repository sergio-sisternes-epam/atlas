# Atlas overlay fixtures

Released Atlas overlays, kept verbatim so that changes to the
contribution contract are tested against what packages actually ship.
Do not edit these files. Add a new directory for a new release instead.

| Directory | Source | Extension slot |
|---|---|---|
| `atlas-tasks-v0.6.0/` | atlas-tasks `v0.6.0`, `contributions/atlas-tasks/SCHEMA.overlay.json` | `atlas_tasks` |
| `atlas-todo-v0.2.0/` | atlas-tasks `v0.2.0`, `contributions/atlas-todo/SCHEMA.overlay.json` | `atlas_todo` |

For each fixture, `scripts/test_overlay_extension.py`:

- installs and compiles it on a SCHEMA 2.0 store;
- installs and compiles it on a SCHEMA 1.0 store;
- installs it on a SCHEMA 1.0 store, upgrades the store to 2.0 and compiles. See `references/paths/schema.md`
(step 3a, **Extension slot**) for the extension slot rule.
