---
name: atlas/paths/landscape
description: On-demand deep research of competitors and symbionts. Updates living comparison memory. Owns landscape protostars until promote, terminate, or a research/work branch starts.
path_id: landscape
---

# Path: landscape

## When

User asks to refresh landscape, update competitors, find partners / symbionts, or run a comparison review. The user does **not** have to name targets.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: landscape
path_module: references/paths/landscape.md
intent: refresh catalogue and/or symbiosis
root: <atlas store root>
```

Optional extra names are additive only.

## Procedure

1. **Resolve root** (same as query).
2. **Query living + dead frame first**
   - vision, comparison-correct, competitors, partners/, glossary, microsoft-as-realization
   - `atlas-project/landscape/` protostars
   - terminated exit under `wrong-path-agent-memory-layer/`
   Do not treat terminated pages as current identity.
3. **Deep research** (path does this; do not wait for a target list)
   - Microsoft realization surfaces first
   - then each living class in comparison-correct / competitors
   - then new candidates the search surfaces
   Stop when every class has a sourced note and every new name is living, a protostar, terminated, or an explicit gap.
4. **Classify** with glossary labels: `rival` | `neighbour` | `projector` | `symbiont` | `out-of-frame`. Realization annotates projector.
5. **Write comparison memory**
   - rival / neighbour → `atlas-project/competitors.md`
   - projector / symbiont → `atlas-project/partners/<kebab>.md` (`role` + label)
   - Microsoft surface change → `atlas-project/microsoft-as-realization.md`
   - half-formed / unverified → protostar under `atlas-project/landscape/` (`star_kind` set, `kva: forming`, `growth: true`)
   - identity-risk (out-of-frame as peer) → load discuss path `terminate`; do not add the row
6. **Landscape owns those protostars.** Create, update, promote, or request terminate. Ownership leaves only when a research or work hub is opened on that name; then the protostar `follows` that work and this path must not keep mutating it as owner.
7. **Cite or gap.** Living claims need `origin` / `sources` or an explicit gap line. Do not invent capabilities.
8. **Job test**, not feature counts: can a second team mount, branch, PR, compile?
9. **Compile green.**
10. **log.md** only for structural adds (new partners/landscape folders, first promote of glossary).

## Non-goals

- User-required target list
- Feature-matrix leaderboards
- Second KVA implementation (use discuss terminate)
- Scheduled cron
- Azure adapter code
