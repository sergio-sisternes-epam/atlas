---
type: runbook
title: "Postgres failover"
description: "Promote the Postgres replica when the primary is lost."
created: 2026-10-11
tags: [postgres, database, runbook]
---

## Steps

Promote the standby with the cluster tool, then point the booking API connection string at the new primary. Expect up to forty seconds of failed writes.
