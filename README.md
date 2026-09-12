# Atlas

![Atlas](docs/atlas-banner.jpg)Looking to build a second brain for your agent or skill (yes, agents can have skills) that follows specific structures and can be connected with other brains? 

Look no more. Atlas is a distruted Semantic Knowledge Network build with technologies LLMs already know: git and
markdown, with a SCHEMA and a CLI that ensures adherence and compliance with pre-defined, extensible domains.

Compatible with GitHub Copilot, Claude Code, Cursor, Grok, Hermes and any other git-capable LLM harness that APM can target.

| Property | What it is |
| --- | --- |
| Git-based | Stores mount as git submodules in the project. |
| Guardrailed | SCHEMA plus CLI `compile` check shape, frontmatter, and links. |
| Distributed | Pages link across stores with `atlas://`. |
| Clustered | Knowledge groups into logical clusters (work hubs, second-brain slices). |
| Shared or dedicated | Knowledge on consumer branch `atlas`, or a separate store repo. |
| Recall | Default grep search; BM25 + tgrep as an early preview. |

## Why / what this is not

Atlas operates mainly at storage level, following
[Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format).
Like [Karpathy’s LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f),
it turns working notes into durable linked pages instead of re-deriving
answers from raw files on every question. Atlas `compile` is a later gate:
it checks SCHEMA, frontmatter, and links — it ensure agents are adherening to the expected structure. Unlike Karpathy, it does separate raw and wiki. Building the leafs "wiki" is part of what you do, when you want and where you need.

Source code, tickets, and designs are systems of record. RAG is good at surfacing information from pre-defined data sources. A central ontology is bad at branch, conflict, and merge. Atlas allows to analyse Systems Of Record and give meaning to them. To treat
each session’s decisions as git history so agents can share a graph without
pretending only one story is true, connecting them to all your Systems Of Record. The graph can span repositories: stores
mount as git submodules, pages link with `atlas://`, and SCHEMA plus the CLI
keep agents from breaking the contract.


> The value is not only in connecting the dots at the surface (the *what*),
> but the trail of memories, decisions, and experiences LLMs create as they
> produce (the *why*).

Atlas is a root APM skill bundle with a deterministic Python CLI. The `okf`
package remains the format authority and a separate dependency. Atlas does not
replace `okf`, phone home, or auto-author claims without an agent. Runtime
detail lives in `SKILL.md`. For Semantic Knowledge Recall (SMR), It ships with a default `grep-enhanced`  search cli and a BM25+tgrep early preview SMR driver.

Atlas is not enforcing a *Semantic Knowledge Organisation (SMO)*. It ships with a simple base SCHEMA that an LLM can customise with the help of `dicuss@atlas` and `atlas@atlas`. But how you organise it is entirely up to you.

Atlas is not an optimised or closed Semantic Knowledge Organisation (SMO), an Enterprise distributed Semantic Knowledge Recall (SMR)  or an Ontology solution. These capabilities can, and should, be built on top of Atlas if the use case requires it.

## Install

Requires APM CLI 0.30.0 or newer and Python 3.10 or newer. Don't forget to set your target harness.

```bash
apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas
apm install atlas@atlas --target copilot
apm install atlas@atlas --target claude
```

> IMPORTANT: Package dependencies are linked to @atlas. If you do not register the marketplace with this exact name, transient dependency installation will fail.

## Use

After install, invoke Atlas in an agent session with `/atlas`. It ships
`getting-started` and `help`. Ask those first; Atlas loads the rest.

```text
/atlas getting-started
/atlas How can I get started?
/atlas I need help on how to use it
```

Starting is asking Atlas how to do it. It comes with its own Atlas and skill modules to help you through the process.

## Modules

| Module | What it does |
| --- | --- |
| Getting started | First-run onboarding: how to mount, init, and ask Atlas. |
| Help | How to use Atlas; ask Atlas how to do the next step. |
| Init | Scaffold a new Atlas in the active git repository. |
| Query | Find and answer from an Atlas store. |
| Remember | Persist experiences, decisions, lessons, and recipes. A basic Sematic Knowledge Organisation (SMO). |
| Work | Open, update, or close work hubs. |
| Landscape | Research competitors and symbionts into comparison memory. |
| Schema | Create, install, or uninstall SCHEMA overlays. Combine with the transient `discuss skill for `best results. |
| Configure | Inspect and select Semantic Memory Recall. |

## Related

- [`okf`](https://github.com/sergio-sisternes-epam/okf) — format authority
- [`atlas-atlas`](https://github.com/sergio-sisternes-epam/atlas-atlas) — companion process-memory store
- [`discuss`](https://github.com/sergio-sisternes-epam/discuss) — optional companion for wrong-frame termination

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, validation, and release
handoff. Report vulnerabilities through a
[private security advisory](https://github.com/sergio-sisternes-epam/atlas/security/advisories/new).

## License

Atlas is licensed under the [Apache License 2.0](LICENSE), Copyright 2026
Sergio Sisternes. The separately distributed `okf` dependency remains under
its own Apache-2.0 license and notice.
