---
type: decision
title: "Adopt the Tide cache for timetable lookups"
description: "Timetable reads go through the in-memory Tide cache with a 90 second TTL."
created: 2026-10-11
tags: [cache, timetable]
relates_to:
  - path: "services/timetable-service.md"
    kind: related
---

## Decision

All timetable lookups read through Tide, an in-memory cache in front of the timetable service. Entries live for 90 seconds.

## Rationale

Sailing timetables change a few times a day, but the booking pages read them thousands of times a minute. A short TTL keeps fares and departure times fresh enough for passengers.
