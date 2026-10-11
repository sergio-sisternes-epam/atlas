---
type: lesson
title: "Forecast drift after a timetable release"
description: "The demand forecast drifted when sailing identifiers changed."
created: 2026-10-11
tags: [forecast, lesson]
relates_to:
  - path: "atlas://example.invalid/larkspur/research-atlas/analytics/demand-forecast.md"
    kind: related
  - path: "atlas://example.invalid/larkspur/archive-atlas/notes/forecast-v1.md"
    kind: supersedes
---

## Lesson

The autumn timetable release moved several departures, which changed their sailing identifiers. The forecast treated them as new sailings with no history and under-predicted demand by a third for two weeks.
