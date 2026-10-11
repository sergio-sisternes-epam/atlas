---
type: runbook
title: "Fail over from Coinpurse"
description: "Switch card payments to the secondary acquirer when Coinpurse is down."
created: 2026-10-11
tags: [payments, runbook]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/services/payment-gateway.md"
    kind: related
---

## Steps

When Coinpurse authorisation errors pass 5 % for five minutes, switch the `payments-secondary-acquirer` flag in Beacon. The adapter then sends new charges to the secondary acquirer and keeps the same idempotency keys.
