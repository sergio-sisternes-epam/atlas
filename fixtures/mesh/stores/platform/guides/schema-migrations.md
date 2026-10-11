---
type: guide
title: "Schema migrations with Keelhaul"
description: "How to write and roll out database migrations with the Keelhaul tool."
created: 2026-10-11
tags: [postgres, database]
relates_to:
  - path: "decisions/bookings-partitioning.md"
    kind: related
---

## Steps

Write each migration as a Keelhaul script with an up and a down step. Migrations that touch the bookings table must create the next monthly partition first.
