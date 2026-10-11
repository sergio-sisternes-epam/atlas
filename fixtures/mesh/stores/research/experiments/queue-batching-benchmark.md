---
type: experiment
title: "Ferry queue batching benchmark"
description: "Throughput of booking consumers with batch sizes from 1 to 100."
created: 2026-10-11
tags: [queue, experiment, benchmark]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/decisions/ferry-queue.md"
    kind: related
---

## Result

Batches of 25 commands gave four times the consumer throughput of single messages, with p95 latency still under one second. Above 50, one poison message delayed the whole batch.
