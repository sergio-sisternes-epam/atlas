---
title: "atlas_optimise.py"
description: "Generated reference for the standalone atlas_optimise.py helper at v0.13.0-beta.13."
sidebar:
  label: "atlas_optimise.py"
  order: 30
source:
  - scripts/atlas_optimise.py
source_sha:
  scripts/atlas_optimise.py: 89efbe16ebe9c2c628bce082263aed813ab153f2
source_tag: v0.13.0-beta.13
generated: true
---

This page is generated from the Atlas helper at `v0.13.0-beta.13`. Do not edit it manually.

`atlas_optimise.py` is a standalone helper. It is not an `atlas.py` command. The operator runs it through the [atlas-optimise module](/atlas/modules/atlas-optimise/). Install and compile never run it.

```text
python3 <atlas-skill>/scripts/atlas_optimise.py ...
```

## Help output

Exact output of `python3 <atlas-skill>/scripts/atlas_optimise.py --help`:

```text
usage: atlas_optimise.py [-h] {plan,apply} ...

atlas-optimise helper (operator-chosen; never on install or compile).

positional arguments:
  {plan,apply}
    plan        dry-run: list tasks per top-level folder; writes nothing in the store
    apply       apply auto tasks (+ opt-in / confirmed) from a plan.json

options:
  -h, --help    show this help message and exit
```

## Subcommand plan

Exact output of `python3 <atlas-skill>/scripts/atlas_optimise.py plan --help`:

```text
usage: atlas_optimise.py plan [-h] --root ROOT --target TARGET [--json] [--out-dir OUT_DIR]
                              [--subject-folder SUBJECT_FOLDER]
                              [--optimise-mode {full,custom,incremental,path}]
                              [--since-hours SINCE_HOURS] [--custom-tree CUSTOM_TREE]
                              [--tidy-only] [--auto-verbatim] [--fill-sensible]
                              [--cost-ceiling COST_CEILING] [--pilot]

options:
  -h, --help            show this help message and exit
  --root ROOT           Atlas store root
  --target TARGET       folder inside the store, or . for the store root
  --json                print the full JSON result
  --out-dir OUT_DIR     write plan.json, receipt.json, and tasks/<folder>.md here (must be outside
                        the store)
  --subject-folder SUBJECT_FOLDER
                        operator-named subject folder as <folder>:<stem>; plans confirm-class
                        moves
  --optimise-mode {full,custom,incremental,path}
                        path (default, fill on), full (target must be .; serial only), custom
                        (--custom-tree prefixes), or incremental (git commit window)
  --since-hours SINCE_HOURS
                        incremental committer-clock window in hours (default 24). Also filters
                        custom mode. Refused on path and full.
  --custom-tree CUSTOM_TREE
                        custom mode path prefix inside the store; repeatable. Refused on path and
                        full. With incremental, intersects the git window.
  --tidy-only           tidy repairs only; do not plan fill tasks
  --auto-verbatim       opt in: verbatim evidence-pack fill may be auto. Confirm stays the
                        default.
  --fill-sensible       name the default posture: useful same-folder gists when evidence supports;
                        residual missing_gist stays OK. Does not force every indexed page.
  --cost-ceiling COST_CEILING
                        max pages examined in the resolved scope (default 200)
  --pilot               record this run as a pilot. The receipt still does not authorize fleet
                        apply.
```

## Subcommand apply

Exact output of `python3 <atlas-skill>/scripts/atlas_optimise.py apply --help`:

```text
usage: atlas_optimise.py apply [-h] --root ROOT --target TARGET [--json] --plan PLAN
                               [--include-opt-in] [--confirm CONFIRM]

options:
  -h, --help         show this help message and exit
  --root ROOT        Atlas store root
  --target TARGET    folder inside the store, or . for the store root
  --json             print the full JSON result
  --plan PLAN        plan.json produced by plan
  --include-opt-in   also apply opt-in tasks (suffix renames)
  --confirm CONFIRM  apply this confirm-class task id
```

See the [CLI reference overview](/atlas/reference/cli/) for the invocation form.
