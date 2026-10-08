---
title: What is Atlas?
description: Atlas is a storage-level knowledge substrate for agents. Learn what it is and what it is not.
source:
  - README.md
  - SKILL.md
  - apm.yml
source_sha:
  README.md: 504c2d65ab2b42dabe8a456d0ce08d9ca85f3de7
  SKILL.md: 95d1b0e3f9963df2a3a0023c3062b840cce63e0a
  apm.yml: 6e853cb45104aebe86c615c94e88a1f27ae5ebe2
source_tag: v0.13.0-beta.13
---

Atlas is a distributed Semantic Knowledge Network.
It uses technologies that large language models (LLMs) already know: git and markdown.
A SCHEMA and a CLI keep agents inside pre-defined, extensible domains.

## The idea

Atlas works mainly at storage level.
It follows the Open Knowledge Format (OKF).
It turns working notes into durable, linked pages.
The agent does not need to work out the same answer from raw files for every question.

Source code, tickets and designs are *systems of record*.
Atlas lets you analyse those systems and give them meaning.
It keeps the decisions of each session as git history.
So agents can share a graph without pretending that only one story is true.
The graph can span repositories:

- A *store* is a git repository, or a branch, that holds Atlas pages.
- Stores mount as git submodules in your project.
- Pages link across stores with `atlas://` links.
- The SCHEMA and the CLI stop agents from breaking the contract.

> The value is not only in connecting the dots at the surface (the *what*),
> but the trail of memories, decisions, and experiences LLMs create as they
> produce (the *why*).

## How it is built

Atlas is a root APM skill bundle with a deterministic Python CLI.
A *skill* is a package of instructions that an agent loads.
The Atlas skill routes each request to one *module*.
A module is one procedure for one intent, such as recall or remember.
See [Modules](/atlas/modules/).

The `okf` package is the format authority.
It is a separate dependency.
Atlas does not replace `okf` and does not re-implement its format rules.

Atlas ships a simple base SCHEMA.
An agent can customise it, with help from the companion skill `discuss` and from Atlas.
How you organise your knowledge is up to you.

## Recall

*Semantic Knowledge Recall (SMR)* means finding knowledge again.
Search stays `grep` until you turn recall on.
The opt-in profile is `atlas:ranked`, which uses FTS5 full-text search.
`atlas:tgrep` is advanced and limited.
See the [`configure`](/atlas/modules/configure/) module.

## What Atlas is not

- Atlas does not enforce a *Semantic Knowledge Organisation (SMO)*.
  It is not an optimised or closed SMO.
- It is not an enterprise distributed Semantic Knowledge Recall system.
- It is not an ontology solution.
- It does not replace `okf`.
- It does not phone home. It has no telemetry.
- It does not write claims by itself. An agent always authors claims.

You can build those capabilities on top of Atlas if your use case needs them.

## Next steps

- [Install Atlas](/atlas/start/install/).
- Walk the [first journey](/atlas/start/first-journey/).
- [Choose where your knowledge lives](/atlas/start/choose-storage/).
