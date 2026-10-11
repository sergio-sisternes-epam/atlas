---
type: concept
title: "Idempotency keys"
description: "A per-booking key that lets consumers drop duplicate commands."
created: 2026-10-11
tags: [booking, payments]
---

## Definition

An idempotency key is a UUID minted by the booking API for each booking attempt. Consumers store the keys they have processed for seven days and drop a command whose key they have already seen.
