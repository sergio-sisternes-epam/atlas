---
type: decision
title: "Beacon serves feature flags"
description: "Feature flags are evaluated by the Beacon flag service, never by config files."
created: 2026-10-11
tags: [flags, release]
---

## Decision

Every feature flag lives in Beacon. Services evaluate flags through the Beacon client, which caches rules for thirty seconds.

## Rationale

Config-file flags needed a deploy to change. Beacon lets the duty engineer switch a flag off during an incident in seconds.
