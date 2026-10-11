---
type: reading
title: "Reading notes on retry storms"
description: "Notes on why synchronised retries overload a recovering service."
created: 2026-10-11
tags: [reading, payments]
relates_to:
  - path: "../../elsewhere/retry-paper.md"
    kind: related
  - path: "atlas://platform-atlas/concepts/backpressure.md"
    kind: related
---

## Notes

When many clients retry on the same schedule, a recovering service sees load spikes that knock it over again. Exponential backoff with jitter spreads the retries out. Load shedding at the edge protects the core.
