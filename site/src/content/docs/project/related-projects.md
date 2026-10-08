---
title: Related projects
description: "Projects that work with Atlas: okf, atlas-atlas and discuss."
sidebar:
  order: 5
source:
  - README.md
  - SKILL.md
source_sha:
  README.md: 504c2d65ab2b42dabe8a456d0ce08d9ca85f3de7
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
source_tag: v0.13.0-beta.13
---

Atlas works with three related projects.

| Project | Role |
| --- | --- |
| [`okf`](https://github.com/sergio-sisternes-epam/okf) | The format authority. Atlas does not re-implement its rules. Ask `okf` format-only questions. |
| [`atlas-atlas`](https://github.com/sergio-sisternes-epam/atlas-atlas) | The companion process-memory store. It is the default store of the Atlas skill. |
| [`discuss`](https://github.com/sergio-sisternes-epam/discuss) | An optional companion skill. Its `terminate` path handles wrong-frame exits, when you explicitly drop a comparison or thesis. |

## okf

`okf` defines the Open Knowledge Format (OKF).
Atlas stores follow OKF v0.2.
`okf` is a separate dependency with its own Apache-2.0 licence and notice.

## atlas-atlas

`atlas-atlas` is the store that the Atlas skill uses for its own process memory.
It mounts at `<git-root>/.atlas/github.com/sergio-sisternes-epam/atlas-atlas`.
The [`mount`](/atlas/modules/mount/) module mounts it when needed.

## discuss

If you explicitly kill a comparison or thesis, the agent loads `discuss` and uses its `terminate` path.
If `discuss` is not installed, the agent stops and tells you that this path needs the companion skill.
`discuss` can also help an agent customise the base SCHEMA.
