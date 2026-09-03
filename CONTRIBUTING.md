# Contributing to Atlas

## Local setup

Use Python 3.10 or newer and APM CLI 0.29.0 or newer.

```bash
python3 -m pip install -r scripts/requirements.txt
```

The APM dependency is private. Configure an APM GitHub credential with
read-only access to `sergio-sisternes-epam/okf`; do not store tokens in this
repository.

## Validate a change

Run every repository-owned Python test and verify that all release-version
surfaces agree:

```bash
python3 scripts/run_tests.py
python3 scripts/release_readiness.py
```

Then verify the pinned dependency and APM integrity:

```bash
apm install --frozen --target agent-skills
apm audit --ci --no-policy --no-fail-fast --no-drift
```

The source audit omits install-replay drift because this repository combines a
root skill bundle with local `.apm` review skills. CI runs the full drift audit
after installing Atlas into each disposable consumer target.

Pull requests run the Python tests but skip package and consumer jobs. Those
secret-dependent jobs run only after merge or through a reusable workflow call,
so pull-request code never receives `APM_READ_TOKEN`.

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

Generated release notes are the current baseline. A changelog, signed tags, and
provenance attestations are optional hardening unless repository or
organisational policy makes them mandatory. Archive checksums and marketplace
artifacts are not applicable while Atlas publishes no release assets.
