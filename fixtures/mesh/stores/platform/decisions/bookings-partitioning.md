---
type: decision
title: "Partition the bookings table by sailing month"
description: "The Postgres bookings table is partitioned by the month of the sailing."
created: 2026-10-11
tags: [postgres, database]
---

## Decision

The bookings table in Postgres is partitioned by sailing month. Old partitions are detached after eighteen months and moved to cold storage.

## Rationale

Queries almost always filter on a sailing date, so monthly partitions keep indexes small and vacuum fast.
