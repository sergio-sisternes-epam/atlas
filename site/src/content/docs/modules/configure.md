---
title: configure
description: Inspect, upgrade, select or disable the recall policy of an Atlas store through the CLI.
sidebar:
  order: 14
source:
  - references/paths/configure.md
  - SKILL.md
  - references/help/index.md
source_sha:
  references/paths/configure.md: b740ad4a729424368c7011080f32ac3d88c20487
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  references/help/index.md: 1c24522c138d839d8ac9a3a02fa562d59790c893
source_tag: v0.13.0-beta.13
---

The `configure` module sets how a store answers recall searches.
A *store* is a git repository (or branch) that holds Atlas knowledge pages.
*Recall* is how the agent finds knowledge in a store.
A recall *profile* (also called a preset) is a named search engine setup, such as `atlas:ranked`.
The store's contract file (`SCHEMA.json` or `CONTRACT.json`) records which profile is active.
`configure` is store-owner work.

## When

Use `configure` to:

- inspect the recall capabilities of a store;
- upgrade a store from SCHEMA 1.0 to 2.0;
- select a recall profile;
- disable recall;
- rebuild a recall index.

Do not use it to find evidence. Use [`recall`](/atlas/modules/recall/) for that.
Do not use it to install skill types. Use [`schema`](/atlas/modules/schema/) for that.

## What it does

1. **Resolve the root** with the [`mount`](/atlas/modules/mount/) module. The agent always passes `--root`.
2. **Inspect** the current state:

   ```text
   python3 <atlas-skill>/scripts/atlas.py recall status --root <root> --json
   python3 <atlas-skill>/scripts/atlas.py recall profiles --root <root> --json
   python3 <atlas-skill>/scripts/atlas.py recall show --root <root> --json
   ```

3. **Preview an upgrade** (SCHEMA 1.0 stores only). Unknown root keys block the upgrade. The agent shows you the preview before any apply.

   ```text
   python3 <atlas-skill>/scripts/atlas.py schema upgrade --to 2.0 --dry-run --root <root> --json
   ```

4. **Apply the upgrade** only after you, the owner, choose it. This writes SCHEMA 2.0 and a store-local `atlas-compat-v1` contribution. It does not enable recall.

   ```text
   python3 <atlas-skill>/scripts/atlas.py schema upgrade --to 2.0 --apply --root <root> --json
   ```

5. **Activate** a profile, then compile. Without `--profile`, activation selects `atlas:ranked`.

   ```text
   python3 <atlas-skill>/scripts/atlas.py recall activate --root <root> --json
   python3 <atlas-skill>/scripts/atlas.py recall activate --profile atlas:tgrep --root <root> --json
   python3 <atlas-skill>/scripts/atlas.py compile --root <root> --json
   ```

6. **Run a request-scoped search** if needed. A `--profile` on `recall run` applies to that one request. It does not change the stored profile. Partial results need `--allow-partial`.

   ```text
   python3 <atlas-skill>/scripts/atlas.py recall run "<query>" --root <root> --profile atlas:scan --json
   python3 <atlas-skill>/scripts/atlas.py recall run "<query>" --root <root> --allow-partial --json
   ```

7. **Disable** recall if asked. Pages, overlays and caches stay in place.

   ```text
   python3 <atlas-skill>/scripts/atlas.py recall disable --root <root> --json
   ```

### Recall profiles

| Profile | Status |
|---------|--------|
| Default (none active) | Grep. Recall stays disabled until the owner opts in. |
| `atlas:ranked` | The opt-in default for activation. It uses a published FTS5 full-text index and a cheap fingerprint check. On the product benchmark it beats grep on speed and on follow-up reads. |
| `atlas:tgrep` | Advanced and explicit. Its benefits are limited for now. It needs the `tgrep` binary on `PATH`. |

:::note
Installing a contribution is not activation.
A contribution may ship a profile, but the profile stays off until the owner selects it.
:::

## How to ask for it

Ask the agent to show the recall status of a store, to upgrade it to SCHEMA 2.0, to turn on ranked recall, or to disable recall.
The agent mounts the store first, then emits the `configure` card.
To learn about the module without running it, ask "explain configure" or "Atlas help configure".

## Activation card

The agent renders the card as a fenced `text` block after `mount` has set `root`:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: configure
path_module: references/paths/configure.md
intent: <one line>
root: <atlas store root>
```

The card and the loaded module are both required. Without them, Enter is incomplete.

When it finishes, the agent emits an exit receipt.
It records `upgrade` (dry-run, apply or n/a), `preset`, `enabled`, the `compile` exit code and the `tgrep` state.

## Boundaries

- The CLI is the only writer of the contract file and `schema.d/`. Never edit them manually.
- Selection is explicit. Installing a contribution must not enable its profile.
- SCHEMA 1.0 stores, and 2.0 stores with recall disabled, keep the legacy `recall run` behaviour.
- `atlas:tgrep` runs only by command-line arguments against an Atlas-owned index under `.atlas-index/tgrep/`. The index is rebuilt when the projection digest does not match.
  - The agent never runs `tgrep serve`, never writes `serve.json` and never uses `--no-index`.
  - A missing binary fails closed with `tgrep_binary_missing`. A detected `serve.json` fails closed with `tgrep_serve_detected`.
  - The agent does not install `tgrep` for you.
- Partial results need `--allow-partial`. Top-k truncation does not mean the corpus is incomplete.

## Related CLI commands

- [`recall status`](/atlas/reference/cli/recall-status/)
- [`recall profiles`](/atlas/reference/cli/recall-profiles/)
- [`recall show`](/atlas/reference/cli/recall-show/)
- [`recall activate`](/atlas/reference/cli/recall-activate/)
- [`recall disable`](/atlas/reference/cli/recall-disable/)
- [`recall run`](/atlas/reference/cli/recall-run/)
- [`schema upgrade`](/atlas/reference/cli/schema-upgrade/)
- [`compile`](/atlas/reference/cli/compile/)

## Related modules

- [`mount`](/atlas/modules/mount/) resolves `root` first.
- [`recall`](/atlas/modules/recall/) finds evidence with the active profile.
- [`schema`](/atlas/modules/schema/) installs contributions and runs `schema upgrade` before `configure`.
- [`help`](/atlas/modules/help/) explains `configure` without running it.
