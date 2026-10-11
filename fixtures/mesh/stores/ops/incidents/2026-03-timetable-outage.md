---
type: incident
title: "March timetable outage"
description: "Booking pages failed for 38 minutes after the spring timetable release."
created: 2026-10-11
tags: [incident, timetable, cache]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/lessons/cache-stampede.md"
    kind: caused_by
  - path: "atlas://example.invalid/larkspur/ops-atlas/incidents/vendor-breach.md"
    kind: related
---

## Summary

For 38 minutes the booking pages showed no sailings. The spring timetable release expired every Tide cache entry together and the timetable service exhausted its database connections.

## Severity

SEV-1: bookings were impossible on every route.
