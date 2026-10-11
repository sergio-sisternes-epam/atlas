---
type: incident
title: "July storm queue backlog"
description: "Storm cancellations flooded the Ferry queue with rebooking commands."
created: 2026-10-11
tags: [incident, queue, storm]
relates_to:
  - path: "atlas://example.invalid/larkspur/ops-atlas/runbooks/ferry-queue-drain.md"
    kind: related
  - path: "atlas://example.invalid/larkspur/research-atlas/analytics/cancellation-patterns.md"
    kind: related
---

## Summary

A summer storm cancelled forty sailings in an afternoon. Passengers rebooked at once and the Ferry queue reached 90,000 commands. Consumers were scaled up and the backlog cleared in two hours.

## Severity

SEV-2: rebookings delayed.
