---
type: experiment
title: "Tide cache TTL study"
description: "Compared TTLs of 30, 90 and 300 seconds with and without jitter."
created: 2026-10-11
tags: [cache, experiment]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/decisions/tide-cache.md"
    kind: informs
---

## Result

A 90 second TTL kept the hit ratio at 96 % while fares stayed fresh. 300 seconds served stale departure times after delays. Jitter of up to 20 seconds removed the synchronised expiry spike seen after a timetable release.
