# Tech-writer adapter: Atlas documentation site

This file tells documentation tooling how the Atlas documentation site is built and checked.
It lives on the `docs` branch only, so it never ships with the Atlas package on `main`.
Point a run at it with the `adapter_path` override; `project_root` is a worktree of the `docs` branch.

The Atlas sources at a release tag are the only source of truth for page content.
Every page records them in its frontmatter (`source`, `source_sha`, `source_tag`).
Generated pages (`generated: true`) come from `site/scripts/generate.py`; never edit them directly.

```yaml
toolkit: starlight
docs_root: site/src/content/docs
surfaces:
  readme: README.md                        # canonical on main; the site summarises and links
  contributing: CONTRIBUTING.md            # canonical on main; the site summarises and links
  guides: site/src/content/docs/start      # task-oriented start pages (no separate guides folder yet)
  reference: site/src/content/docs/reference
  adrs: none
  release_notes: CHANGELOG.md              # canonical on main at the tag; the site page is generated
frontmatter: starlight-docs + source fields (source, source_sha, source_tag)
build_check: npm --prefix site ci && npm --prefix site run build
verify_commands:
  - npm --prefix site run check:tag-self-test
  - npm --prefix site run check:generated
  - npm --prefix site run check:version
  - npm --prefix site run check:drift
  - npm --prefix site run check:registry
  - npm --prefix site run check:brand
  - npm --prefix site run check:no-microsoft
  - npm --prefix site run check:gitignore
  - npm --prefix site run check:size
  - npm --prefix site run check:links
  - npm --prefix site run check:sanitise
  - npm --prefix site run check:denylist
  - npm --prefix site run check:a11y
toc_ownership: site/astro.config.mjs (starlight.sidebar)
glossary_path: site/src/content/docs/reference/glossary.md   # arrives in a later phase; not present yet
pairing:
  - surface: site/src/content/docs/modules/<id>.md
    artifact: <tag>:references/paths/<id>.md
  - surface: site/src/content/docs/reference/cli/<verb>.md
    artifact: <tag>:scripts/atlas_cli/cli.py
  - surface: site/src/content/docs/project/changelog.md
    artifact: <tag>:CHANGELOG.md
docs_capability: absent
advisory_opt_in: false
advisory_transport: github-pr-comment
```

Notes:

- The Python checks and the generator need an Atlas checkout at the tag in `atlas-src/` (or `ATLAS_SRC`). See `site/README.md`.
- `check:denylist` fails closed unless `DOCS_HOST_DENYLIST` is set; use `DOCS_DENYLIST_MODE=pending-ok` only for pull-request runs.
- `check:links`, `check:no-microsoft` (dist part), `check:sanitise` (dist part) and `check:a11y` need a built `site/dist`.
- The toolchain needs Node 22.23.3 exactly (`site/.nvmrc`).
- `check:size` enforces the final budget in `site/size-budget.json`, including an `svgo` dry run on added SVGs.
  Add `-- --mirror-url <repository url>` to also measure the packed size of a fresh mirror clone, as CI does on pull requests.
