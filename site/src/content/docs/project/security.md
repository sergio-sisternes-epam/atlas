---
title: Security
description: How to report a vulnerability in Atlas privately.
sidebar:
  order: 3
source:
  - README.md
  - CONTRIBUTING.md
  - SKILL.md
source_sha:
  README.md: 504c2d65ab2b42dabe8a456d0ce08d9ca85f3de7
  CONTRIBUTING.md: 4b82aac94ff862293369545c8a0fe1a44e1dbd3e
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
source_tag: v0.13.0-beta.13
---

## Report a vulnerability

Report vulnerabilities privately through a
[private security advisory](https://github.com/sergio-sisternes-epam/atlas/security/advisories/new)
on the Atlas repository.
This uses GitHub private vulnerability reporting.

:::danger
Do not file a public issue for a vulnerability.
:::

## What Atlas does and does not do

These points from the skill help you judge the risk surface:

- Atlas does not phone home. It has no telemetry.
- Atlas does not write claims by itself. An agent always authors claims.
- With no git repository, Atlas refuses to persist anything.
- Mount credentials are scoped to a host.
  Generic public GitHub tokens apply only to `github.com` and `*.ghe.com`.
  Never widen a generic token to an arbitrary mount host.
- Do not store tokens in an Atlas repository.

## Related

- [Contributing](/atlas/project/contributing/)
- [Licence](/atlas/project/licence/)
