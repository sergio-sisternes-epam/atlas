---
type: lesson
title: "Poison message in the Ferry queue"
description: "A malformed booking command blocked a consumer until it was moved to the dead-letter queue."
created: 2026-10-11
tags: [queue, incident]
relates_to:
  - path: "decisions/ferry-queue.md"
    kind: related
  - path: "atlas://example.invalid/larkspur/ops-atlas/runbooks/ferry-queue-drain.md"
    kind: related
---

## Lesson

One booking command with a truncated sailing identifier failed on every delivery. The consumer retried it forever and the queue stopped moving.

## Fix

After five failed deliveries a command now goes to the dead-letter queue for a human to inspect.
