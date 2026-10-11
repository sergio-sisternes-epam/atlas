---
type: concept
title: "Backpressure between booking services"
description: "How consumers slow producers when the queue grows."
created: 2026-10-11
tags: [queue]
relates_to:
  - path: "decisions/ferry-queue.md"
    kind: related
---

## Definition

When the Ferry queue depth passes a threshold, the booking API answers new requests with a retry-after header instead of publishing. This sheds load at the edge rather than inside the consumers.
