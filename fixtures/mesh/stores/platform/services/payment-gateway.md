---
type: service
title: "Payment gateway adapter"
description: "Adapter in front of the Coinpurse payment provider."
created: 2026-10-11
tags: [payments, coinpurse]
relates_to:
  - path: "concepts/idempotency-keys.md"
    kind: related
---

## Overview

The payment gateway adapter wraps Coinpurse, the card payment provider. It retries a failed authorisation up to three times.

## Contract

Every charge request carries the booking idempotency key, so a retry can never charge a passenger twice.
