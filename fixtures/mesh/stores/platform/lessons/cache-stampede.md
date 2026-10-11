---
type: lesson
title: "Tide cache stampede on timetable release"
description: "Every Tide entry expired at once after a timetable release and the timetable service fell over."
created: 2026-10-11
tags: [cache, timetable, incident]
relates_to:
  - path: "decisions/tide-cache.md"
    kind: related
  - path: "atlas://example.invalid/larkspur/ops-atlas/incidents/2026-03-timetable-outage.md"
    kind: related
  - path: "atlas://example.invalid/larkspur/research-atlas/experiments/cache-ttl-study.md"
    kind: related
---

## Lesson

A timetable release invalidated every Tide entry at the same moment. All booking pages missed the cache together and the timetable service ran out of database connections.

## Fix

TTLs now carry random jitter of up to 20 seconds, so entries expire spread out over time.
