# Atlas docs branch

This branch holds the sources of the Atlas documentation site only.
The site lives under `site/`.
The site uses Astro and Starlight.
The site workflow lives under `.github/workflows/docs-site.yml`.
Both arrive in later pull requests.

## Relationship to `main`

The Atlas product lives on `main`.
The product includes the skill, the CLI and the references.
The docs build against Atlas release tags (`vX.Y.Z`).
The build fetches these tags from this same repository.

## Rules

- Never merge this branch into `main`. Never merge `main` into this branch. The histories are unrelated on purpose.
- Never tag this branch. Release tags belong to `main` only.
- The default branch of the repository stays `main`. Never change it.
- Commit sources only. Do not commit built output (`site/dist/`, `site/.astro/`). Do not commit `node_modules/`, archives, video or heavy binaries. Keep images small. Prefer SVG.
- Changes arrive by pull request into `docs`. Maintainers squash-merge each pull request.
- Install Atlas from the marketplace or from a pinned release tag. Never install Atlas from this branch.

## Published site

The site is not published yet.
The site URL will be `https://sergio-sisternes-epam.github.io/atlas/` once publishing is approved.

## Licence

This branch uses the Apache-2.0 licence.
This is the same licence as `main`.
See the [licence file on `main`](https://github.com/sergio-sisternes-epam/atlas/blob/main/LICENSE).
