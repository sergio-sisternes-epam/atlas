---
name: atlas/paths/schema
description: Create, install, validate, or uninstall SCHEMA overlays. CLI is the only writer. Load before any schema create/update/install work.
path_id: schema
---

# Path: schema

## When

Any of:

- New Atlas root needs its first contract file (`init` writes `CONTRACT.json` on new stores; shipped 0.13.0-beta stores keep `SCHEMA.json`)
- A **project** needs a bespoke type or extra SCHEMA keys before a skill exists
- A **skill** ships types (`protostar`, `kva`, …) into its own store or a host Atlas
- An overlay must be upgraded or removed
- Compile is red on overlay / core-clash / undeclared root writes

Not for writing knowledge pages (use **remember** / **work**). Not for OKF format rules (use skill **okf**).

## Enter (required — Atlas `activation_card: on`)

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: schema
path_module: references/paths/schema.md
intent: <one line>
root: <atlas store root>
```

Then **read this file**. Missing card or unloaded module ⇒ incomplete Enter.

Other paths may call `atlas compile` as a tool. They must not hand-edit the store's single contract file (`SCHEMA.json` or `CONTRACT.json`) or `schema.d/`.

## Choose the verb

| Situation | Verb |
|-----------|------|
| Empty folder, no contract file | `init` then, if this is a skill store, `schema install` |
| Project idea, not a skill yet | `schema new <id>` then `schema install` a local overlay file when types exist |
| Skill contribution into a store | `schema install <source>` |
| Contribution shipped in an APM package | `apm install <owner>/<pkg>#vX.Y.Z`, then `schema install <pkg-root>/contributions/<id>` (step 3a) |
| Overlay required-keys changed | `schema install … --force` |
| Remove a contribution | `schema uninstall <id>` |
| Check merge / clashes only | `compile` |
| SCHEMA 1.0 → 2.0 envelope (does not enable recall) | `schema upgrade` then path `configure` |
| Opt a store's memory severity in or out (the operator asked) | `schema memory-rung --set info\|warn\|error` |

Never skip compile after a write.

## Hard rules

1. **CLI is the only writer** of the store's single contract file (`SCHEMA.json` or `CONTRACT.json`) and `schema.d/`. Do not open those files in an editor and save. If `python3 <atlas-skill>/scripts/atlas.py` is missing, **stop** (fail-closed).
2. **Init writes core only.** No skill namespaces (`kva`, …) in the born SCHEMA.
3. **Overlays add types.** They must not set `atlas_id`, `compile`, `structure`, `schema_version`, or redeclare core `templates.by_type` entries (`work`, `document`, `experience`, …).
4. **Author the overlay outside the store**, then install. Legal places to *compose* JSON: a skill `contributions/<id>/SCHEMA.overlay.json`, or a temp file you pass to `schema install`. Illegal: editing `schema.d/<id>.json` in place.
5. **Receipt is evidence.** Compile fails if a receipt lists a path that is not under `schema.d/` and not under `claimed_folders`.
6. **Knowledge folders stay free layout.** Do not `schema new --claim` a folder just because pages live there.

## Procedure

### 0. Resolve root

Same as recall. Always pass `--root`. Omitting `--root` uses cwd, not the skill mount.

### 1. Birth a store

```bash
python3 <atlas-skill>/scripts/atlas.py init --root <root>
```

Refuses to overwrite without `--force`. Then compile.

Skill-owned process memory: immediately install that skill’s overlay (step 3). Do not copy keys into SCHEMA.json.

### 2. Project overlay (no skill yet)

```bash
python3 <atlas-skill>/scripts/atlas.py schema new <kebab-id> --root <root> [--claim <folder>]
```

- `<kebab-id>` like `experiments` or `ignite-2026` (not `Not_Kebab`).
- `--claim` is optional and repeatable. Only claim folders this overlay’s CLI writes will own.
- This writes `schema.d/<id>.json` + `.receipt.json`. It does **not** yet add types.

To add types: author an overlay file (shape below) with the same `contribution_id`, then `schema install <file> --root <root>` (`--force` if the overlay already exists).

### 3. Install a contribution

Source is one of:

- a file `SCHEMA.overlay.json`
- a directory containing that file
- `contributions/<id>/` in a skill package (overlay + optional `templates/<newtype>.md`)

```bash
python3 <atlas-skill>/scripts/atlas.py schema install <source> --root <root> [--force]
```

`--force` is required when this overlay’s `templates.by_type.*.frontmatter.required` changed. Without it, install exits 2.

Install copies **new-type** templates only. It will not overwrite core `templates/work.md`.

Install, `schema uninstall` and `schema upgrade --apply` share the store lock `.atlas-upgrade.lock`. If the lock is present, each exits 2 and writes nothing. Atlas never removes a lock it did not create, whatever the contract version. Retry when the other command finishes. A lock left by an interrupted install, uninstall or upgrade stays until an operator deletes it. Delete it only when no Atlas command is running and the store's contract file and `schema.d/` have been checked.

### 3a. Shipping an Atlas overlay in an APM package

`SCHEMA.overlay.json`, `schema.d/` and the `schema` verbs predate the contract/schema-layer split: here 'schema' means the store contract, not the `*.schema.md` memory layer. The CLI verbs and file names stay as they are in this release.

A package ships its Atlas overlay inside its APM skill package at `contributions/<id>/SCHEMA.overlay.json` (plus optional `templates/<newtype>.md`).

`apm install` only installs the skill package. It never mounts the overlay into any Atlas store. Mounting is a separate, explicit `schema install` against the store the user names (`--root`). Do not install into a store the user did not name; ask if unclear.

1. Install the package pinned to a tag:

   ```bash
   apm install <owner>/<pkg>#vX.Y.Z
   ```

   Example: `apm install sergio-sisternes-epam/atlas-tasks#v0.6.2`. A marketplace install (`apm install <plugin>@<marketplace>`) works too, if the package is listed in a marketplace you added. Do not assume any particular package is listed.

2. Locate the package root (verified with APM 0.33; APM 0.30+ uses the same layout):
   - `apm_modules/<owner>/<pkg>/` in the project where you ran `apm install`. This is the full package, always present after a project install. Prefer it.
   - The deployed skill copy, e.g. `.agents/skills/<pkg>/` for the `agent-skills` target. It exists only when the package's targets overlap the project's targets (otherwise APM skips deployment with a warning). Do not rely on it.
   - `apm.lock.yaml` records `resolved_ref`, `resolved_commit` and `version` for each dependency, plus the `deployments` paths. Use it to confirm which tag you are about to mount.
   - Check that `<pkg-root>/contributions/<id>/SCHEMA.overlay.json` exists before installing.

3. Mount and compile:

   ```bash
   python3 <atlas-skill>/scripts/atlas.py schema install <pkg-root>/contributions/<id> --root <store>
   python3 <atlas-skill>/scripts/atlas.py compile --root <store>
   ```

**Upgrade.** After `apm install <owner>/<pkg>#vNEW` or `apm update`, the store keeps the old overlay until you re-run `schema install` from the new package root. Add `--force` when that overlay's required frontmatter keys changed (install exits 2 otherwise). Then compile.

**Remove.** `apm uninstall <owner>/<pkg>` removes the package from `apm_modules/` and the deployed skill copy, but leaves `schema.d/<id>.json` and its receipt in every store. Remove the contribution with `schema uninstall <id> --root <store>`, then compile.

**Extension slot.** An Atlas overlay may carry at most one package-metadata root key: the `contribution_id` with `-` replaced by `_` (see "Root keys an overlay may carry" below). Atlas never reads it. Packages keep their descriptive and operational contract (folders, statuses, commands) in their README, not in the slot.

**Receipt.** Record the package ref (tag or commit from `apm.lock.yaml`) on the Exit receipt `source:` line.

### 4. Uninstall

```bash
python3 <atlas-skill>/scripts/atlas.py schema uninstall <id> --root <root>
```

Deletes `schema.d/<id>.json` and paths on that overlay’s receipt (overlay + templates the CLI copied). Does **not** delete pages the agent authored later. Compile may still see those pages; unknown `type` stays legal under OKF. If they used types that lived only on the overlay, the CLI prints a warning.

Uninstall takes the store lock (see step 3). While it is held, uninstall exits 2 and deletes nothing.

### 5. Compile (always)

```bash
python3 <atlas-skill>/scripts/atlas.py compile --root <root>
```

Effective SCHEMA = the store's single core contract file (`SCHEMA.json` or `CONTRACT.json`) ∪ `schema.d/*.json`.

| Issue id | Meaning | Exit |
|----------|---------|------|
| `overlay_core_clash` | Overlay set a forbidden core key | 2 |
| `overlay_core_type` | Overlay redeclared a core `by_type` | 2 |
| `overlay_key_clash` | Two overlays claim the same extra key or type | 2 |
| `overlay_extension` | Extension slot is not a JSON object (2.0 store) | 2 |
| `overlay_undeclared_root` | Receipt lists a path outside claimed prefixes / `schema.d/` | 2 |
| `overlay_receipt` | Installed overlay has no receipt | 2 |
| `overlay_json` / `overlay_id` | Unreadable overlay or id ≠ filename | 2 |

Exit 2 → fix via **schema** verbs, not a text edit. Then compile again. Do not claim the store is healthy.

### 6. log.md

Append one bullet only when schema layout changed (init, first overlay, uninstall). Not for every type tweak.

### 7. Memory rung (opt-in only)

```bash
# --set accepts exactly one of: info, warn, error
python3 <atlas-skill>/scripts/atlas.py schema memory-rung --set info --root <root>
python3 <atlas-skill>/scripts/atlas.py schema memory-rung --set warn --root <root>
python3 <atlas-skill>/scripts/atlas.py schema memory-rung --set error --root <root>
```

This is the **only** writer of `memory.rung`; it edits whichever single contract file the store has (`SCHEMA.json` or `CONTRACT.json`). It sets `rung` (plus the fixed
`layers` and `legacy_types` lists) and does not retype any page. Do not
hand-edit the contract file to change the rung. Path `memory-migrate` must not call
this command unless the operator explicitly asked to opt the rung from `info`
toward `warn` or `error`; its `assess` and `inventory` modes never change the
rung. Absent `memory.rung` means `info` — existing stores stay unaffected
until an operator opts in.

## Overlay file to author (outside the store)

```json
{
  "contribution_id": "discuss",
  "claimed_folders": ["protostars"],
  "templates": {
    "by_type": {
      "protostar": {
        "file": "templates/protostar.md",
        "frontmatter": {
          "required": ["type", "title", "created"],
          "recommended": ["kva", "status"]
        },
        "sections": { "required": [], "recommended": ["Pending", "Origin"] }
      }
    }
  }
}
```

Skill package layout:

```text
contributions/<id>/
  SCHEMA.overlay.json
  templates/<newtype>.md    # optional; copied on install for new types only
```

Root keys an overlay may carry:

- **Contract keys**: `contribution_id`, `claimed_folders`, `templates`, `types`, `bindings`, `presets`.
- **One extension slot** for package metadata. Its key is the `contribution_id` with `-` replaced by `_` (`atlas-tasks` → `atlas_tasks`, `discuss` → `discuss`). The value must be a JSON object. Atlas checks that it is an object and that no other overlay claims the same key. It is **never** merged into the effective contract and core never reads it. Ids whose slot would equal a core or envelope key (`memory`, `atlas-release`, `templates`, …) get no slot. Do not make agent behaviour depend on the slot. Keep the package's operational contract in its own docs.
  - **Minimum reader.** The slot is accepted from Atlas 0.13.1. Older readers merge it as a generic root key, so on a contract envelope 2.0 (`schema_version` 2.0) store their compile fails `schema_v2` (`'<slot>' was unexpected`). The contract stamp stays `0.13.0` and does not record this. A 2.0 store that holds an Atlas overlay with a slot, installed directly or kept through `schema upgrade --to 2.0`, needs Atlas >= 0.13.1 to compile. On a 2.0 store, `schema install` prints a note when it accepts a slot.
  - **Roll back or mix versions.** Before running Atlas < 0.13.1 on such a store, reinstall a slot-free release of the overlay (atlas-tasks >= 0.6.2) with `schema install`, or `schema uninstall` it. Then compile with the older Atlas.
  - 1.0 stores (`schema_version` 1.0) are unaffected: older readers accept extra overlay root keys there.
- **Other extra root keys** (for example `kva`):
  - On a 1.0 store, they are allowed if they are **not** already in the core contract file and **not** used by another overlay.
  - On a 2.0 store, `schema install` rejects them (`contribution-v1`). `schema upgrade --to 2.0` blocks until they are removed.

Test an Atlas overlay on both a 1.0 store and a `init --schema-version 2.0` store before you release it.

## Worked sequences

**New project Atlas, later a custom type**

1. `init --root <root>`
2. `schema new my-idea --root <root>`
3. Write `SCHEMA.overlay.json` beside the skill or in tmp (`contribution_id: my-idea`, new types only)
4. `schema install <that-file> --root <root>`
5. `compile --root <root>`

**Skill store (discuss, autogenesis, …)**

1. `init --root <skill>/references/atlas` if missing
2. `schema install <skill>/contributions/<id> --root <skill>/references/atlas`
3. `compile`

**Host Atlas receiving a skill**

Same as skill store, but `--root` is the **host**. Do not dump skill folders at the host root; only claimed prefixes plus `schema.d/`.

**Shipping an Atlas overlay in an APM package** (step 3a)

1. `apm install <owner>/<pkg>#vX.Y.Z` (pinned tag)
2. Find the package root under `apm_modules/<owner>/<pkg>/`; confirm the tag in `apm.lock.yaml`
3. `schema install <pkg-root>/contributions/<id> --root <store>`
4. `compile --root <store>`

## Exit receipt

```text
skill: atlas
path: schema
root: …
verb: init | schema new | schema install | schema uninstall | compile
source: <owner>/<pkg>#vX.Y.Z | local    # optional; schema install only (step 3a)
compile: exit N
```

Incomplete if the verb wrote SCHEMA by hand, CLI was missing and you continued, or compile stayed red.

## Non-goals

- Hand-edit `SCHEMA.json` / `schema.d/`
- Sandbox overlays that skip compile
- A catalog skill named schema
- Migrating live in-place SCHEMA keys (`kva`) — separate work
- Changing OKF reserved names or closing the type enum
