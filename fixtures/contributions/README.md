# Contribution overlay fixtures

Released contribution overlays, kept verbatim so that changes to the
contribution contract are tested against what packages actually ship.
Do not edit these files. Add a new directory for a new release instead.

| Directory | Source | Extension slot |
|---|---|---|
| `atlas-tasks-v0.6.0/` | atlas-tasks `v0.6.0`, `contributions/atlas-tasks/SCHEMA.overlay.json` | `atlas_tasks` |
| `atlas-todo-v0.2.0/` | atlas-tasks `v0.2.0`, `contributions/atlas-todo/SCHEMA.overlay.json` | `atlas_todo` |

`scripts/test_overlay_extension.py` installs each fixture on SCHEMA 1.0 and
SCHEMA 2.0 stores and compiles them. See `references/paths/schema.md`
(Contribution overlays) for the extension slot rule.
