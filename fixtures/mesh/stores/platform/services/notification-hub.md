---
type: service
title: "Notification hub"
description: "Sends booking confirmations and sailing alerts by SMS and email through Heron."
created: 2026-10-11
tags: [notifications, sms, email]
---

## Overview

The notification hub sends booking confirmations, boarding reminders and sailing cancellation alerts. SMS and email both go through Heron, the messaging provider.

## Throughput

Heron accepts 50 SMS per second per account; the hub queues anything above that.
