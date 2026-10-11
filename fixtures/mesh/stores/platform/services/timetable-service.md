---
type: service
title: "Timetable service"
description: "Serves sailings, departure times and vessel assignments."
created: 2026-10-11
tags: [timetable, api]
relates_to:
  - path: "decisions/tide-cache.md"
    kind: related
---

## Overview

The timetable service owns sailings, departure times and which vessel runs each route. Writers publish a new timetable release twice a season.

## Reads

Reads go through the Tide cache; the service itself handles only cache misses.
