# Contributing to Atlas

## Issues and pull requests

Use the GitHub issue templates in `.github/ISSUE_TEMPLATE/` for bugs and
feature requests. Report vulnerabilities through a
[private security advisory](https://github.com/sergio-sisternes-epam/atlas/security/advisories/new);
do not file public issues for them.

External substantive work needs a linked issue first. Maintainer-authored
small docs or maintenance may skip that wait.

A human must approve the scope before an agent implements the change, except
for maintainer-authored small docs or maintenance. The pull request author
owns any agent-generated diffs and must not open the pull request as an
unattended GitHub author.

## Local setup

Use Python 3.10 or newer and APM CLI 0.30.0 or newer.

```bash
python3 -m pip install -r scripts/requirements.txt
```

Register the catalog before installing dependencies:

```bash
apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas
```

The `--name` flag is required. Do not use alias `me` or the default
`atlas-marketplace` name. OKF remains private; configure an APM GitHub credential
with read-only access to `sergio-sisternes-epam/okf` and do not store tokens in
this repository.

Atlas mount credentials are host-scoped. Generic public GitHub tokens apply
only to `github.com` and `*.ghe.com`. For GHES automation, set `GH_HOST` to the
exact server hostname and use `GH_ENTERPRISE_TOKEN` or
`GITHUB_ENTERPRISE_TOKEN`; a stored `gh auth login --hostname <host>`
credential is also supported. Never broaden a generic token to an arbitrary
mount host.

## Validate a change

Run every repository-owned Python test and verify that all release-version
surfaces agree:

```bash
python3 scripts/run_tests.py
python3 scripts/release_readiness.py
```

Then register the catalog. APM 0.30.0 records marketplace plugins under
`_marketplace/<catalog>/<name>` in the manifest but writes git coordinates into
`apm.lock.yaml`, so source `apm install --frozen` and `apm audit --ci` cannot
round-trip this pin. CI therefore scans committed primitives in the source
checkout and runs full lockfile plus install-replay drift audits after
installing Atlas into each disposable consumer:

```bash
apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas
apm audit --no-policy --no-drift
```

Pull requests from branches in this repository run the Python tests, the source
primitive scan, and full install-replay drift audits in disposable consumers.
The source scan receives `APM_READ_TOKEN` but does not run `apm install`, so the
checked-out deployment remains unchanged. Pull requests from forks cannot
receive repository secrets and therefore skip the APM and consumer gates; they
still run the Python tests.

The CI workflow additionally installs the checked-out package into disposable
consumers for both the shared Agent Skills target and APM's stable multi-runtime
target set.

## CI credential

Repository Actions require an `APM_READ_TOKEN` secret. Use a fine-grained token
or GitHub App installation token with `Contents: read` for the private Atlas
and OKF repositories. The workflow exposes it only through APM's
`GITHUB_APM_PAT_SERGIO_SISTERNES_EPAM` environment variable.

## Release handoff

Atlas follows semantic versioning. While the package remains below `1.0.0`, use
a patch increment for compatible fixes and documentation, and a minor increment
for new capability or a compatibility-breaking package or CLI contract.

1. Update the release version in `apm.yml`, `SKILL.md`,
   `scripts/atlas_cli/__init__.py`, the reusable workflow default, and both
   workflow examples under `references/ci/`.
2. Run the validation commands above. `scripts/release_readiness.py` blocks
   when any version surface disagrees.
3. Merge through the normal review process.
4. Run **Atlas CI** manually against the exact `main` commit intended for the
   release. Its final **Release readiness decision** job must report the
   candidate SHA and `pre_tag_decision=ready to tag`.
5. Create and push the matching immutable tag, `vX.Y.Z`, against that exact
   commit. Never tag a different commit merely because it has the same version.
6. The release workflow reruns every repository test, frozen APM installation,
   source audit, and disposable-consumer audit. It then checks version/tag
   alignment and `main` ancestry before creating the GitHub release.
7. Give the EPAM Marketplace maintainer the source repository, immutable tag or
   compatible version range, description, and tags.

### Failed-tag recovery

Pushed release tags are immutable: do not move, overwrite, or delete them. If
validation fails for a pushed tag before a GitHub release is created, correct
the problem on `main`, increment the package version, repeat the pre-tag gate,
and publish a new tag. Leave the failed tag without a release and record the
failure in the associated issue or pull request.

If validation passed and only GitHub Release creation failed because of a
provider outage or permission problem, rerun the failed workflow for the same
tag after restoring the provider. Do not rebuild from a different commit.

The source package workflow does not edit the marketplace catalog. Atlas is
private, so the marketplace validation identity and intended consumers must
also receive read access before registration can pass.

Atlas is distributed directly from its immutable Git tag. `apm pack` exports
the dependency bundle for this root-skill project, not the Atlas skill itself,
so release automation must not publish that output as an Atlas package.

Record user-visible changes under `Unreleased` in `CHANGELOG.md`. GitHub release
notes remain generated from merged pull requests. Signed tags and provenance
attestations are optional hardening unless repository or organisational policy
makes them mandatory. Archive checksums and marketplace artifacts are not
applicable while Atlas publishes no release assets.
