---
name: atlas/paths/configure
description: Inspect, upgrade, select, or disable Semantic Memory Recall. Load before changing SCHEMA recall policy.
path_id: configure
---

# Path: configure

## When

Store-owner work to inspect recall capabilities, upgrade SCHEMA 1.0 to 2.0, select a recall preset, disable recall, or rebuild a recall index. Not for finding evidence (use **query**). Not for installing skill types (use **schema**). Install is never activation.

## Enter (required — Atlas `activation_card: on`)

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

Then **read this file**. Missing card or unloaded module ⇒ incomplete Enter.

## Hard rules

1. **CLI is the only writer** of `SCHEMA.json` and `schema.d/`.
2. **Explicit selection.** Installing a contribution must not enable its preset.
3. **Legacy until opt-in.** SCHEMA 1.0 and 2.0 with `recall.enabled=false` keep `atlas search` compatibility behaviour.
4. **tgrep is argv-only.** Use an Atlas-owned `.atlas-index/tgrep/` index rebuilt when the projection digest mismatches. Never `tgrep serve`, never write `serve.json`, never `--no-index`. Missing binary fails closed (`unsupported_capability: tgrep_binary_missing`). Detected `serve.json` fails closed (`tgrep_serve_detected`). Do not auto-install tgrep.
5. **Partial results** need `--allow-partial`. Do not treat top-k truncation as incomplete corpus.
6. **Defaults.** Leave recall disabled (grep) until the owner opts in. `atlas recall activate` defaults to `atlas:ranked` (published FTS5 + cheap fingerprint; product bench beats grep on speed and follow-up tokens). `atlas:tgrep` is an explicit advanced profile with limited benefits until serve/subset-rank (protostar `p-tgrep-serve-and-subset-rank`). Never `tgrep serve` without a new pin. Provenance: atlas-atlas lesson `lessons/2026-09-09-opt-in-ranked-after-fast-path.md`.

## Procedure

1. **Resolve root** (path `mount`). Always pass `--root`.
2. **Inspect**
   ```bash
   python3 <atlas-skill>/scripts/atlas.py recall status --root <root> --json
   python3 <atlas-skill>/scripts/atlas.py recall profiles --root <root> --json
   python3 <atlas-skill>/scripts/atlas.py recall show --root <root> --json
   ```
3. **Upgrade preview** (1.0 stores only)
   ```bash
   python3 <atlas-skill>/scripts/atlas.py schema upgrade --to 2.0 --dry-run --root <root> --json
   ```
   Unknown root keys block upgrade. Preview must be shown before apply.
4. **Apply upgrade** only after the owner selects it. This writes SCHEMA 2.0, a store-local `atlas-compat-v1` contribution, and **does not enable recall**.
   ```bash
   python3 <atlas-skill>/scripts/atlas.py schema upgrade --to 2.0 --apply --root <root> --json
   ```
5. **Activate** a supported profile. Omitting `--profile` selects `atlas:ranked`. Use `atlas:tgrep` only as an explicit advanced profile (`tgrep` binary on `PATH`; never serve).
   ```bash
   python3 <atlas-skill>/scripts/atlas.py recall activate --root <root> --json
   python3 <atlas-skill>/scripts/atlas.py recall activate --profile atlas:tgrep --root <root> --json
   python3 <atlas-skill>/scripts/atlas.py compile --root <root> --json
   ```
6. **Request-scoped search** (does not persist the preset)
   ```bash
   python3 <atlas-skill>/scripts/atlas.py search "<query>" --root <root> --profile atlas:scan --json
   python3 <atlas-skill>/scripts/atlas.py search "<query>" --root <root> --allow-partial --json
   ```
7. **Disable** leaves pages, overlays, and caches in place.
   ```bash
   python3 <atlas-skill>/scripts/atlas.py recall disable --root <root> --json
   ```

## Exit receipt

```text
skill: atlas
skill_path: …
path: configure
root: …
upgrade: dry-run | apply | n/a
preset: <id or none>
enabled: true | false
compile: atlas compile --root …  (exit)
tgrep: argv-index | tgrep_binary_missing | tgrep_serve_detected
```
