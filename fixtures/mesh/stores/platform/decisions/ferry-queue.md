---
type: decision
title: "Ferry queue carries every booking command"
description: "Booking commands travel over the Ferry queue with at-least-once delivery."
created: 2026-10-11
tags: [queue, booking]
relates_to:
  - path: "concepts/idempotency-keys.md"
    kind: related
---

## Decision

The booking API publishes each booking command to the Ferry queue. Consumers acknowledge after the write commits, so delivery is at-least-once.

## Rationale

At-least-once delivery means a command can arrive twice. Every consumer must therefore deduplicate with idempotency keys before charging or seating a passenger.
