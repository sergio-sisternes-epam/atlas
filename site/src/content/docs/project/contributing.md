---
title: Contributing
description: "How to contribute to Atlas: issues, pull requests, local setup, validation and the release handoff."
sidebar:
  order: 2
source:
  - CONTRIBUTING.md
  - README.md
source_sha:
  CONTRIBUTING.md: 4b82aac94ff862293369545c8a0fe1a44e1dbd3e
  README.md: 504c2d65ab2b42dabe8a456d0ce08d9ca85f3de7
source_tag: v0.13.0-beta.13
---

This page summarises how to contribute to Atlas.
The full guide is [`CONTRIBUTING.md` on GitHub](https://github.com/sergio-sisternes-epam/atlas/blob/main/CONTRIBUTING.md).
If this summary and that file disagree, the file wins.

## Issues and pull requests

- Use the GitHub issue templates for bugs and feature requests.
- Report vulnerabilities privately. Do not file public issues for them.
  See [Security](/atlas/project/security/).
- External substantive work needs a linked issue first.
  Small documentation or maintenance changes by maintainers may skip that wait.
- A human must approve the scope before an agent implements a change.
  The same exception applies to small maintainer changes.
- The pull request author owns any diff that an agent generates.
  Do not open a pull request as an unattended GitHub author.

## Local setup

You need Python 3.10 or newer and APM CLI 0.30.0 or newer.

```bash
python3 -m pip install -r scripts/requirements.txt
apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas
```

- The `--name atlas` flag is required.
  Do not use the alias `me` or the default `atlas-marketplace` name.
- Do not store tokens in the repository.
  Public github.com consumers do not need a personal access token.
- When a matching immutable tag exists, you may install that tag for release checks:

  ```bash
  apm install sergio-sisternes-epam/atlas#vX.Y.Z
  ```

- Mount credentials are scoped to a host.
  Generic public GitHub tokens apply only to `github.com` and `*.ghe.com`.
  For GitHub Enterprise Server automation, set `GH_HOST` to the exact server hostname.
  Then use `GH_ENTERPRISE_TOKEN` or `GITHUB_ENTERPRISE_TOKEN`, or a stored GitHub CLI login for that host.
  Never widen a generic token to an arbitrary mount host.

## Validate a change

Run every Python test in the repository.
Check that all release-version surfaces agree:

```bash
python3 scripts/run_tests.py
python3 scripts/release_readiness.py
```

CI also scans the committed package primitives and installs Atlas into disposable consumer projects.
Pull requests from forks skip the APM and consumer gates, so their readiness job reports `blocked`.
That is expected.

## Release handoff

Atlas follows semantic versioning.
Below `1.0.0`, a patch increment covers compatible fixes and documentation.
A minor increment covers new capability or a breaking change to the package or CLI contract.

In short, maintainers:

1. Update the release version on every version surface, and bring every CI reference up to that version before tagging.
2. Run the validation commands, including `scripts/release_readiness.py --pre-tag`.
3. Merge through normal review.
4. Run Atlas CI on the exact `main` commit for the release, and wait for `pre_tag_decision=ready to tag`.
5. Create and push the matching immutable tag `vX.Y.Z` on that exact commit.
6. Let the release workflow re-verify everything and create the GitHub release.
7. Give the tag and description to the marketplace maintainer.

Pushed release tags are immutable.
If a pushed tag fails validation, fix the problem on `main`, increase the version and publish a new tag.

Record user-visible changes under `Unreleased` in `CHANGELOG.md`.
See the [Changelog](/atlas/project/changelog/).
