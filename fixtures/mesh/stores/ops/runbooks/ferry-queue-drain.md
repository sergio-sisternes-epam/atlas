---
type: runbook
title: "Drain a Ferry queue backlog"
description: "Steps to drain a booking backlog from the Ferry queue safely."
created: 2026-10-11
tags: [queue, runbook]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/decisions/ferry-queue.md"
    kind: related
---

## Steps

1. Check the queue depth panel in Lantern.
2. Scale booking consumers to twelve replicas.
3. If depth still grows, switch on the `booking-intake-pause` flag in Beacon so the booking API answers with retry-after.
4. Inspect the dead-letter queue before switching the flag off.
