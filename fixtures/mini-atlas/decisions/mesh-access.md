---
type: decision
title: "Mesh access modes"
created: 2026-08-23
status: accepted
work_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1
description: "Each mesh entry declares read or read/write."
---

## Decision

Every Atlas entry in a mesh must declare `access: read` or `access: read/write`.

## Rationale

Shared upstream knowledge stays safely read-only while owned Atlases remain mutable.

## Alternatives considered

Implicit write access for all peers was rejected as unsafe for APM-packaged knowledge.

## Consequences

`atlas compile` validates access values; write ops against `read` Atlases hard-fail.
