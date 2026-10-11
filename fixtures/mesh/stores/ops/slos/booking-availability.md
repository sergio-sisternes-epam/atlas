---
type: slo
title: "Booking availability SLO"
description: "The booking API answers successfully for 99.9 % of requests over 28 days."
created: 2026-10-11
tags: [slo, booking]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/services/booking-api.md"
    kind: related
---

## Objective

99.9 % of booking API requests succeed over a rolling 28 days. The error budget is about forty minutes. Retry-after answers from backpressure count as failures.
