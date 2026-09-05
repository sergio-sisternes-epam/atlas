---
name: atlas/paths/work
description: Open, update, or close work hubs (type work) and keep the cluster linked. Load before work_id lifecycle changes.
path_id: work
---

# Path: work

## When

Start, update status, or close a unit of effort tracked by `work_id`.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: work
path_module: references/paths/work.md
intent: <one line>
root: <atlas store root>
```

## Procedure

1. **Resolve root**.
2. **Hub path** — `work/<work_id>.md` with `type: work`, `work_id`, `title`, `status`, `description`, scope/status/outcomes sections as needed.
3. **Status** — use clear values e.g. `draft` | `implementing` | `done` (SCHEMA may extend).
4. **relates_to from hub** — edges to important children (experiences, decisions, plans) with `kind: related` (or tighter kinds when accurate).
5. **relates_to from children** — each child under this effort should include `implements` → this hub (see **remember**).
6. **Close** — set `status: done`; link follow-on work with `related` / `follows` if any; append **log.md**.
7. **Compile** after material hub edits:
   ```bash
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```

## Exit

- Hub path + status + compile exit 0.
- log.md updated on open (optional) and on close (required for structural close).

## Non-goals

- Full session narrative (that is an **experience** via **remember**).
- Search (use **query**).
