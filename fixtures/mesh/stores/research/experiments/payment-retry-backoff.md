---
type: experiment
title: "Payment retry backoff"
description: "Exponential backoff for Coinpurse retries against fixed delays."
created: 2026-10-11
tags: [payments, experiment]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/services/payment-gateway.md"
    kind: related
---

## Result

Exponential backoff with jitter recovered 97 % of transient Coinpurse failures within three attempts. Fixed one second delays caused retry storms when Coinpurse was slow.
