---
type: incident
title: "May double charge"
description: "Some passengers were charged twice when payment retries lacked idempotency keys."
created: 2026-10-11
tags: [incident, payments]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/concepts/idempotency-keys.md"
    kind: related
  - path: "atlas://example.invalid/larkspur/research-atlas/experiments/payment-retry-backoff.md"
    kind: related
---

## Summary

A new code path in the payment gateway adapter retried Coinpurse charges without the booking idempotency key. 212 passengers were charged twice and refunded the same day.

## Severity

SEV-2: money taken in error.
