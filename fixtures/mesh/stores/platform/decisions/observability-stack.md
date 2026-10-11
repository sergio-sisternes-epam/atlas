---
type: decision
title: "Lantern for tracing and metrics"
description: "Lantern collects traces and metrics from every service."
created: 2026-10-11
tags: [observability, tracing]
---

## Decision

Lantern is the single tracing and metrics backend. Each service exports spans with the sailing identifier as an attribute.

## Rationale

One backend means one query language for incident responders and one retention policy of thirty days.
