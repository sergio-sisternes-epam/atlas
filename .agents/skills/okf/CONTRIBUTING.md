# Contributing to OKF

## Local setup

Use APM CLI 0.29.0 or newer. This package has no runtime dependencies and does
not need a source lockfile. A consumer installation creates its own
`apm.lock.yaml` with the exact OKF revision and deployed-file hashes.

## Validate a change

Check every release-version surface against the current revision:

```bash
python3 scripts/release_readiness.py --commit "$(git rev-parse HEAD)"
```

Audit tracked source files:

```bash
git ls-files -z | while IFS= read -r -d '' file; do
  apm audit --file "$file" --no-policy
done
```

Then install the checked-out package into a disposable consumer and run
`apm audit --ci --no-policy --no-fail-fast`. CI exercises both the shared
`agent-skills` target and APM's stable multi-runtime target set.

`apm compile --validate` and `apm pack` are not validation gates for this
package. OKF uses the supported root `SKILL.md` source-package shape, has no
`.apm/` compilation input, and is distributed directly from its immutable Git
tag rather than as a packed dependency bundle.

## Release handoff

OKF follows semantic versioning. While the package remains below `1.0.0`, use a
patch increment for compatible fixes and documentation, and a minor increment
for new capability or a compatibility-breaking format contract.

1. Update the package version in `apm.yml`, `SKILL.md`, `README.md`, and
   `CHANGELOG.md`.
2. Run the local validation above and merge through the normal review process.
3. Run **OKF CI** manually against the exact `main` commit intended for release.
   Its final job must report the candidate SHA and
   `pre_tag_decision=ready to tag`.
4. After separate explicit approval, create and push the matching immutable
   `vX.Y.Z` tag, or `vX.Y.Z-<identifier>` prerelease tag, against that exact
   commit.
5. The tag workflow reruns every gate, verifies that the new tag exactly equals
   the current `main` tip, classifies stable versus prerelease from the tag, and
   creates the categorized GitHub Release.

Never move, overwrite, or delete a pushed release tag. If validation fails
before a GitHub Release is created, fix `main`, increment the package version,
repeat the pre-tag gate, and publish a new tag. If only GitHub Release creation
fails because of a provider outage or permission problem, rerun the failed
workflow for the same tag.

OKF is a private source package. Consumers need Contents: read access to this
repository through an APM-supported Git credential. The release workflow needs
no custom secret: the repository `GITHUB_TOKEN` is read-only during validation
and receives `contents: write` only in the release-creation job.

## Repository protection

After the CI workflow is present on `main`, protect it with the **Release
metadata**, **APM package integrity**, and both **Consumer install** status
checks. Require branches to be current, and block direct pushes, force pushes,
and deletion. Protect `v*` tags with a ruleset that restricts creation to
release maintainers and blocks tag updates and deletion.

This repository is owned by a GitHub user and currently has no organization
team or second eligible reviewer. A team-backed `.github/CODEOWNERS` file and a
mandatory approval rule cannot be established without fabricating ownership or
making every pull request unmergeable. Before declaring the full release
governance baseline complete, transfer the repository to an organization with
a real owning team, grant that team write access, add CODEOWNERS, and require
code-owner review and at least one approval.
