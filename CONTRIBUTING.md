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

Run the source test first:

```bash
python3 scripts/test_schema_governance.py
```

Then verify the pinned dependency and APM integrity:

```bash
apm install --frozen --target agent-skills
apm audit --ci --no-policy --no-fail-fast --no-drift
```

The source audit omits install-replay drift because this repository combines a
root skill bundle with local `.apm` review skills. CI runs the full drift audit
after installing Atlas into each disposable consumer target.

The CI workflow additionally installs the checked-out package into disposable
consumers for both the shared Agent Skills target and APM's stable multi-runtime
target set.

## CI credential

Repository Actions require an `APM_READ_TOKEN` secret. Use a fine-grained token
or GitHub App installation token with `Contents: read` for the private Atlas
and OKF repositories. The workflow exposes it only through APM's
`GITHUB_APM_PAT_SERGIO_SISTERNES_EPAM` environment variable.

## Release handoff

1. Update `version` in `apm.yml` and merge the validated change to `main`.
2. Create the matching immutable tag, such as `v0.8.12`.
3. The release workflow verifies that the tag is reachable from `main`, reruns
   CI, checks manifest/tag alignment, and creates the GitHub release.
4. Give the EPAM Marketplace maintainer the source repository, immutable tag or
   compatible version range, description, and tags.

The source package workflow does not edit the marketplace catalog. Atlas is
private, so the marketplace validation identity and intended consumers must
also receive read access before registration can pass.

Atlas is distributed directly from its immutable Git tag. `apm pack` exports
the dependency bundle for this root-skill project, not the Atlas skill itself,
so release automation must not publish that output as an Atlas package.
