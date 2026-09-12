# atlas

Atlas keeps agent process memory in git: markdown pages, a SCHEMA, and a CLI
that compiles the graph.

## Why / what this is not

Atlas follows [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
and the compile-once idea in [Karpathy’s LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
Knowledge is written once, linked, and reused — not rediscovered from raw files
on every question.

Source code and tickets are systems of record. RAG is good at the *what*. A
central ontology is bad at branch, conflict, and merge. Atlas treats each
session’s decisions as git history so agents can share a graph without
pretending only one story is true.

> The value is not only in connecting the dots at the surface (the *what*),
> but the trail of memories, decisions, and experiences LLMs create as they
> work.

Atlas is a root APM skill bundle with a deterministic Python CLI. The `okf`
package remains the format authority and a separate dependency. Atlas does not
replace `okf`, phone home, or auto-author claims without an agent. Runtime
detail lives in `SKILL.md`.

## Install

Requires APM CLI 0.30.0 or newer and Python 3.10 or newer.

```bash
apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas
apm install atlas@atlas
```

After the source owner publishes an immutable tag matching the `version` in
`apm.yml`, you may also install that tag:

```bash
apm install sergio-sisternes-epam/atlas#vX.Y.Z
```

Then install CLI dependencies in the environment that runs Atlas:

```bash
python3 -m pip install -r <atlas-skill>/scripts/requirements.txt
```

## Use

```bash
python3 <atlas-skill>/scripts/atlas.py search "authentication decision" \
  --root <atlas-root> --json
```

## Modules

- **Query** — Find and answer from an Atlas store.
- **Remember** — Persist experiences, decisions, lessons, and recipes.
- **Work** — Open, update, or close work hubs.
- **Landscape** — Research competitors and symbionts into comparison memory.
- **Schema** — Create, install, or uninstall SCHEMA overlays.
- **Configure** — Inspect and select Semantic Memory Recall.
- **Init** — Scaffold a new Atlas in the active git repository.

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
