---
type: runbook
title: "Clear a notification backlog"
description: "What to do when SMS reminders queue up behind the Heron rate limit."
created: 2026-10-11
tags: [notifications, sms, runbook]
relates_to:
  - path: "atlas://example.invalid/larkspur/platform-atlas/services/notification-hub.md"
    kind: related
  - path: "atlas://example.invalid/larkspur/ops-atlas/runbooks/does-not-exist.md"
    kind: related
---

## Steps

When the hub queue holds more than 10,000 SMS, pause marketing messages first, then ask Heron support to lift the account limit for the day. Cancellation alerts always go first.
