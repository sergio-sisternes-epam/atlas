---
type: runbook
title: "Flush the Tide cache safely"
description: "How to flush Tide without stampeding the timetable service."
created: 2026-10-11
tags: [cache, runbook]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/lessons/cache-stampede.md"
    kind: related
---

## Steps

Never flush all of Tide at once. Flush one route prefix at a time and wait two minutes between routes, watching timetable service connections in Lantern.
