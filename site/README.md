# Atlas documentation site

The sources of the Atlas documentation site.
The site uses Astro 7.3.6 and Starlight 0.42.5, with the atlas-style 0.1.1 brand layer.
It documents one Atlas release tag at a time, currently `v0.13.0-beta.13`.

This folder lives on the orphan `docs` branch.
Never merge this branch into `main`, and never merge `main` into it.

## Prerequisites

- Node 22.23.3 exactly (`.nvmrc` and `engines`).
- Python 3.10 or newer, for the generator and the Python checks.
- git.

## Set up

Run these from the repository root.

1. Install the site dependencies from the lockfile:

   ```bash
   cd site && npm ci && cd ..
   ```

2. Fetch the Atlas release tag into `atlas-src/` (git-ignored, read-only input):

   ```bash
   git clone --depth 1 --branch v0.13.0-beta.13 https://github.com/sergio-sisternes-epam/atlas.git atlas-src
   ```

3. Create a project-local Python environment and install the Atlas CLI requirements:

   ```bash
   python3 -m venv site/.venv
   site/.venv/bin/python -m pip install -r atlas-src/scripts/requirements.txt
   ```

   The npm scripts use `$ATLAS_PYTHON` if set, else `site/.venv/bin/python` if it exists, else `python3`.
   They read the Atlas checkout from `$ATLAS_SRC`, else `../atlas-src`.

## Generate

Some pages are generated from the Atlas sources: the CLI command pages, the module index, the changelog and `src/data/atlas-build.json`.
Never edit a page with `generated: true`; re-run the generator instead.

```bash
site/.venv/bin/python site/scripts/generate.py --atlas-src atlas-src          # write
site/.venv/bin/python site/scripts/generate.py --atlas-src atlas-src --check  # V1: fail on drift
```

Inside `site/`, `npm run generate` and `npm run check:generated` do the same.

## Build

Run these inside `site/`.

```bash
npm run build           # B1: build into site/dist
npm run build:preview   # same, with DOCS_PREVIEW=1 (noindex + "Preview build" banner)
npm run dev             # local dev server
```

## Checks

Every check exits non-zero on failure. Run them inside `site/`.

| Script | Check | Needs |
| --- | --- | --- |
| `check:tag-self-test` | V0 SemVer sort self-test | — |
| `check:tag` | V0 resolve the tag (`--tag vX.Y.Z` to validate one; without it, needs `origin/main`) | network |
| `check:generated` | V1 generated pages are up to date | `atlas-src` |
| `check:version` | V2 `apm.yml` version = tag = `atlas-build.json` | `atlas-src` |
| `check:drift` | V3 every `source` path exists and matches `source_sha`; `source_tag` = tag | `atlas-src` |
| `check:registry` | V4 module pages = SKILL.md Path registry; CLI pages = Click tree | `atlas-src` |
| `check:links` | V5 internal links and anchors in `dist` | build |
| `check:no-microsoft` | V7 no Microsoft-owned links (`:source` / `:dist` for one part) | build for `:dist` |
| `check:sanitise` | V8 a+b secrets, hosts, IPs, emails, home paths (allowlist: `scripts/sanitise-allowlist.json`) | build |
| `check:denylist` | V8 c private host deny-list from `DOCS_HOST_DENYLIST` | build |
| `check:brand` | V9 token file hash, no raw colours or lengths, no caution asides | — |
| `check:a11y` | V10 axe in light and dark (report in `site/test-reports/`) | build, Chromium |
| `check:size` | V13 final size budget (`size-budget.json`), see below | git, svgo |
| `check:gitignore` | no tracked build output, caches or inputs | git |
| `check:source` | V0 self-test, V1–V4, V9, V7 sources, gitignore | `atlas-src` |
| `check:dist` | V5, V7 dist, V8 a+b | build |

Notes:

- `check:denylist` fails closed when `DOCS_HOST_DENYLIST` is unset.
  Set `DOCS_DENYLIST_MODE=pending-ok` to get a warning instead; CI does this on pull requests only.
  The deny-list is a secret: never commit it, and never print its entries.
- `check:a11y` uses `PLAYWRIGHT_CHROMIUM_EXECUTABLE` when set; otherwise run `npx playwright install chromium` first.
- External links (V6) are checked in CI with lychee.

### Size budget (V13)

The values in `size-budget.json` are final. `check:size` prints one table row per measure, with the value, the warn and fail thresholds and the result.

| Measure | Warn | Fail |
| --- | --- | --- |
| (a) build output, caches, `site/public/pagefind/`, archives, media or binaries added | — | any |
| (b1) one raster image (`png`, `jpg`, `jpeg`, `webp`, `avif`) | — | 200 KiB |
| (b2) any one file, `site/package-lock.json` included | — | 500 KiB |
| (c) bytes added by the diff, lockfile excluded (lockfile reported separately) | — | 1 MiB |
| (d) packed `docs` history | 3 MiB | 5 MiB |
| (e) `svgo` dry run would save 10% or more on an added SVG; any raster added | — | yes |
| (f) packed size of a fresh `git clone --mirror` of the repository | 6 MiB | 8 MiB |

- `-- --base <ref>` sets the diff base (default `origin/docs`); `--skip-diff` skips (a), (b), (c) and (e).
- (d) measures a fresh `--single-branch --branch docs` clone with `-- --history-url <url>`.
  Without it, it measures the history of HEAD as a stand-in, plus a projection that commits the working tree in a temp repository.
- (e) reports the brand copies in `brand_verbatim` but never fails on them, because they must stay byte-identical to the brand source.
- (f) runs only with `-- --mirror-url <url>`. CI runs it on pull requests. Locally, use `https://github.com/sergio-sisternes-epam/atlas.git`.
  A GitHub mirror clone also fetches `refs/pull/*`; the check reports how many.

## Continuous integration

`.github/workflows/docs-site.yml` runs on pushes and pull requests to `docs`, and on manual dispatch.
The `build-and-check` job resolves the tag, checks out Atlas into `atlas-src`, runs every check above, builds the site and runs gitleaks, lychee and axe.
Pull requests upload a noindex `docs-preview` artefact; it is not a deployment.

The `deploy` job is gated and is always skipped today.
It runs only on a manual dispatch with `deploy: true` on `docs`, and only when the repository variable `DOCS_PUBLISH_ENABLED` is `true`.
The repository owner sets that variable after the pre-publish gate, after setting Pages to deploy from GitHub Actions, and after protecting the `github-pages` environment.

## Writing pages

- Write British, controlled English: short sentences, active voice, plain words.
- Derive each page only from the Atlas sources it lists in `source`. Record each blob hash with `git -C atlas-src rev-parse HEAD:<path>`.
- Show the CLI only as `python3 <atlas-skill>/scripts/atlas.py ...`.
- Use the `note`, `tip` and `danger` asides only.
- Style only with atlas-style tokens (`var(--token)`); never edit `src/styles/atlas-tokens.css`.
