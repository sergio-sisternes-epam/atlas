# atlas

Atlas is a durable OKF v0.2 knowledge substrate for agent process memory,
decisions, work hubs, and project knowledge graphs.

## Why / what this is not

Atlas is a root APM skill bundle with a deterministic Python CLI. Use it to
query stores, remember knowledge, track work, refresh landscape, and govern
schema on durable OKF graphs.

The `okf` package remains the format authority and a separate dependency.
Atlas does not replace `okf`, phone home, or auto-author claims without an
agent. Runtime detail lives in `SKILL.md`.

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
