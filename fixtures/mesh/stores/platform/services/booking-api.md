---
type: service
title: "Booking API"
description: "Public API that accepts bookings and publishes them to the Ferry queue."
created: 2026-10-11
tags: [booking, api]
relates_to:
  - path: "decisions/ferry-queue.md"
    kind: implements
---

## Overview

The booking API accepts seat and vehicle bookings from the website and the mobile app. It validates the sailing identifier, reserves capacity and publishes a booking command to the Ferry queue.

## Limits

The API is rate limited to 200 requests per second per client.
