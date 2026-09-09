---
name: atlas/paths/schema
description: Create, install, validate, or uninstall SCHEMA overlays. CLI is the only writer. Load before any schema create/update/install work.
path_id: schema
---

# Path: schema

## When

Any of:

- New Atlas root needs its first `SCHEMA.json`
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

Other paths may call `atlas compile` as a tool. They must not hand-edit `SCHEMA.json` or `schema.d/`.

## Choose the verb

| Situation | Verb |
|-----------|------|
| Empty folder, no `SCHEMA.json` | `init` then, if this is a skill store, `schema install` |
| Project idea, not a skill yet | `schema new <id>` then `schema install` a local overlay file when types exist |
| Skill contribution into a store | `schema install <source>` |
| Overlay required-keys changed | `schema install … --force` |
| Remove a contribution | `schema uninstall <id>` |
| Change the core required-section budget | `schema configure --max-required-sections-per-type <N>` |
| Discover native validation support | `schema capabilities --json` |
| Check merge / clashes only | `compile` |

Never skip compile after a write.

## Hard rules

1. **CLI is the only writer** of `SCHEMA.json` and `schema.d/`. Do not open those files in an editor and save. If `python3 <atlas-skill>/scripts/atlas.py` is missing, **stop** (fail-closed).
2. **Init writes core only.** No skill namespaces (`kva`, …) in the born SCHEMA.
3. **Overlays add types.** They must not set `atlas_id`, `compile`, `structure`, `schema_version`, or redeclare core `templates.by_type` entries (`work`, `document`, `experience`, …).
4. **Author the overlay outside the store**, then install. Legal places to *compose* JSON: a skill `contributions/<id>/SCHEMA.overlay.json`, or a temp file you pass to `schema install`. Illegal: editing `schema.d/<id>.json` in place.
5. **Receipt is evidence.** Compile fails if a receipt lists a path that is not under `schema.d/` and not under `claimed_folders`.
6. **Knowledge folders stay free layout.** Do not `schema new --claim` a folder just because pages live there.

## Procedure

### 0. Resolve root

Same as query. Always pass `--root`. Omitting `--root` uses cwd, not the skill mount.

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
Before writing, install validates the complete candidate schema merge, budget,
receipts, and template destinations. It does not require existing knowledge
pages to conform to newly installed rules; migrate those pages and compile.

New receipts track SHA-256 ownership of copied templates. Reinstall retains
ownership, and upgrades replace only this contribution's unchanged managed
files. An edited file or conflicting unowned file is an error even with
`--force`. An identical unowned file may stay in place, but matching bytes do
not transfer ownership. Legacy receipts remain readable; without hashes they
cannot authorize template replacement. Resolve conflicts explicitly outside
the install operation; never use uninstall/reinstall as an upgrade shortcut.

### 4. Uninstall

```bash
python3 <atlas-skill>/scripts/atlas.py schema uninstall <id> --root <root>
```

Deletes `schema.d/<id>.json` and unchanged hash-owned templates. Edited,
unowned, and legacy unhashed templates are preserved with visible notes.
Does **not** delete pages the agent authored later. Compile may still see those
pages; unknown `type` stays legal under OKF. If they used types that lived only
on the overlay, the CLI prints a warning.

### 5. Compile (always)

```bash
python3 <atlas-skill>/scripts/atlas.py compile --root <root>
```

Effective SCHEMA = core `SCHEMA.json` ∪ `schema.d/*.json`.

| Issue id | Meaning | Exit |
|----------|---------|------|
| `overlay_core_clash` | Overlay set a forbidden core key | 2 |
| `overlay_core_type` | Overlay redeclared a core `by_type` | 2 |
| `overlay_key_clash` | Two overlays claim the same extra key or type | 2 |
| `overlay_undeclared_root` | Receipt lists a path outside claimed prefixes / `schema.d/` | 2 |
| `overlay_receipt` | Installed overlay has no receipt | 2 |
| `overlay_json` / `overlay_id` | Unreadable overlay or id ≠ filename | 2 |

Exit 2 → fix via **schema** verbs, not a text edit. Then compile again. Do not claim the store is healthy.

### 6. log.md

Append one bullet only when schema layout changed (init, first overlay, uninstall). Not for every type tweak.

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

Extra root keys (for example `kva`) are allowed if they are **not** already on core SCHEMA and **not** used by another overlay.

## Worked sequences

### Opt-in native validation

Feature preflight does not require a mounted store:

```bash
python3 <atlas-skill>/scripts/atlas.py schema capabilities --json
```

Receipt shape (the package version reflects the executable's release surface,
not an assertion that unreleased features have been published):

```json
{
  "ok": true,
  "capability_version": 1,
  "atlas_version": "0.9.1",
  "features": {
    "required_h2_sections": 1,
    "scalar_date_rules": 1,
    "date_order_rules": 1,
    "typed_local_relates_to": 1,
    "core_section_budget_configure": 1,
    "receipt_hash_template_upgrades": 1
  },
  "frontmatter_format": "atlas-minimal"
}
```

Require the needed feature versions before installing an overlay. An older
CLI rejecting this verb does not support the contract.

The born core budget remains six required sections per type. To deliberately
raise it for one store, use the allowlisted operation:

```bash
python3 <atlas-skill>/scripts/atlas.py schema configure \
  --max-required-sections-per-type 7 --root <root> --json
```

The value is a nonnegative integer (zero permits no required sections).
Configuration validates the candidate effective schema and receipts before
atomic replacement of `SCHEMA.json`, preserving every other setting. It
refuses a reduction that invalidates installed overlays. JSON formatting may
be normalized. Overlays still cannot set any `compile` key. Compile after
configuration; configuration does not certify knowledge pages.

Minimal generic overlay, authored **outside** the store:

```json
{
  "contribution_id": "sample-contract",
  "templates": {
    "by_type": {
      "sample-record": {
        "frontmatter": {
          "required": ["type", "title", "started", "ended"],
          "fields": {
            "started": {"type": "date", "unknown": ["Unknown."]},
            "ended": {"type": "date", "unknown": ["Unknown."]},
            "status": {"type": "string", "enum": ["open", "closed", "Unknown."]}
          },
          "date_order": [{"before": "started", "after": "ended", "allow_equal": true}]
        },
        "sections": {
          "enforce": true,
          "required": ["Overview", "Evidence"],
          "require_content": true
        },
        "relates_to": [
          {"kind": "records", "target_types": ["sample-source"], "min": 1, "max": 1}
        ]
      },
      "sample-source": {"frontmatter": {"required": ["type", "title"]}}
    }
  }
}
```

| Declaration | Executable meaning |
|-------------|--------------------|
| `sections.enforce: true` | Require each named, case-sensitive ATX level-two heading exactly once. Optional trailing closing `##` syntax is ignored; extra sections are legal. |
| `sections.require_content: true` | Required section must contain non-whitespace content beyond headings/comments; requires `enforce: true`. `Unknown.` is legitimate explicit content. |
| `frontmatter.fields` | Validate present values as scalar strings from Atlas's existing minimal frontmatter parser. Missing fields are optional unless listed in `required`; existing missing-required warnings remain exit 1. |
| `type: string` | Nonblank scalar, with optional exact string `enum`. |
| `type: integer` / `number` | Signed decimal integer / finite decimal number (number also permits exponent notation). Optional inclusive numeric `minimum`/`maximum`; no implicit range. |
| `type: boolean` | Exact lowercase `true` or `false`. |
| `type: date` | Real calendar date in exact `YYYY-MM-DD` form, or one of the exact strings in optional `unknown`. No implicit unknown token. |
| `frontmatter.date_order` | `before` and `after` must name declared date fields. Known dates ordered inclusively by default; `allow_equal: false` makes order strict. Missing/unknown endpoints skip ordering, not their independent field checks. |
| Per-type `relates_to` rules | Matching explicit `kind` requires existing root-contained concept `.md` targets whose `type` is in `target_types`. External URLs, store escapes, reserved indexes, staging, and templates cannot satisfy the rule. |
| Relation `min` / `max` | Optional inclusive nonnegative bounds on distinct resolved targets for that kind; neither implied if absent. Duplicate target aliases are errors, not extra cardinality. Other kinds remain legal. |

Headings inside backtick or tilde fences and HTML comments do not satisfy
required headings. H1/H2 boundaries terminate section bodies; lower-level
headings alone are not content. Nonempty fenced code can be explicit content.
This is deliberately an ATX-heading contract, not a full Markdown renderer:
Setext headings, blockquotes, and indented code are not required H2 markers.

Use the parser's existing block-list representation for authoritative links:

```yaml
relates_to:
  - path: sources/example.md
    kind: records
```

On a type declaring relation rules, entries must be maps with explicit `kind`;
the legacy `role` alias does not satisfy typed rules. No nested YAML parser or
inline YAML object support is introduced.

Malformed declarations fail as `schema_shape`, not as silently disabled rules.
Native page-rule issue IDs are `required_sections`, `field_contract`,
`date_order`, and `typed_relates_to`; all are critical exit 2 and cannot be
bypassed by inline ignores. Without the corresponding opt-in, existing page
behavior is unchanged. The existing global thin-body gate also still applies.

The synthetic seven-category passing/failing examples under
`fixtures/native-schema/` exercise the configurable budget and missing-body
category failure through the CLI.

**Limits:** compile validates a current snapshot. It cannot prove historical
immutability, evidence truth, authorship, or completeness beyond declared
rules. Receipt hashes are local ownership bookkeeping, not signatures.
Configuration uses atomic single-file replacement; install preflights the full
plan and replaces individual files, not a filesystem-wide atomic transaction.

**Design choices:** opt-in enforcement was chosen over retroactive global
heading gates to preserve legacy pages. Narrow scalar rules were chosen over
a YAML-parser replacement to preserve the frontmatter contract. An allowlisted
core command was chosen over overlay budget overrides to retain core ownership.
Hash-based template ownership was chosen over unconditional `--force` writes
to preserve user edits. Versioned capability receipts were chosen over
package-version inference so consumers can preflight unreleased source builds.
The executable evidence for these choices lives in
`scripts/test_native_schema.py` and `scripts/test_template_upgrades.py`.

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

## Exit receipt

```text
skill: atlas
path: schema
root: …
verb: init | schema new | schema install | schema uninstall | schema configure | compile
compile: exit N
```

Incomplete if the verb wrote SCHEMA by hand, CLI was missing and you continued, or compile stayed red.

## Non-goals

- Hand-edit `SCHEMA.json` / `schema.d/`
- Sandbox overlays that skip compile
- A catalog skill named schema
- Migrating live in-place SCHEMA keys (`kva`) — separate work
- Changing OKF reserved names or closing the type enum
