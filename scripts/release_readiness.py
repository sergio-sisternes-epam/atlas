#!/usr/bin/env python3
"""Validate Atlas release metadata against one manifest version."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER = r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"


@dataclass(frozen=True)
class VersionSurface:
    label: str
    path: str
    pattern: str


# Package surfaces: the in-development package version. These must all agree
# with each other (manifest is the source of truth for "expected").
PACKAGE_SURFACES = (
    VersionSurface("manifest", "apm.yml", rf"^version:\s*({SEMVER})\s*$"),
    VersionSurface("skill", "SKILL.md", rf"^version:\s*({SEMVER})\s*$"),
    VersionSurface(
        "Python CLI",
        "scripts/atlas_cli/__init__.py",
        rf'^__version__\s*=\s*"({SEMVER})"\s*$',
    ),
)

# CI ref surfaces: pinned to the last *tagged* (published) release, not to
# the in-development package version. During a beta line (e.g. package at
# 0.13.0-beta.3 while only v0.13.0-beta has been tagged) these intentionally
# lag behind PACKAGE_SURFACES. They must still agree with *each other*.
CI_SURFACES = (
    VersionSurface(
        "reusable workflow default",
        ".github/workflows/atlas-compile.yml",
        rf"^\s*default:\s*v({SEMVER})\s*$",
    ),
    VersionSurface(
        "copy workflow ref",
        "references/ci/github-actions.compile.yml",
        rf"^\s*ATLAS_REF:\s*v({SEMVER})\s*$",
    ),
    VersionSurface(
        "caller workflow source",
        "references/ci/github-actions.caller.yml",
        rf"^\s*uses:\s*sergio-sisternes-epam/atlas/.+@v({SEMVER})\s*$",
    ),
    VersionSurface(
        "caller workflow input",
        "references/ci/github-actions.caller.yml",
        rf"^\s*atlas_ref:\s*v({SEMVER})\s*$",
    ),
)

SURFACES = PACKAGE_SURFACES + CI_SURFACES


def read_surface(surface: VersionSurface, root: Path = ROOT) -> str:
    content = (root / surface.path).read_text(encoding="utf-8")
    matches = re.findall(surface.pattern, content, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(
            f"{surface.path}: expected one {surface.label} version, found {len(matches)}"
        )
    return matches[0]


def manifest_version(root: Path = ROOT) -> str:
    return read_surface(PACKAGE_SURFACES[0], root)


def validate_versions(
    root: Path = ROOT, require_ci_match_package: bool = False
) -> tuple[str, list[str]]:
    expected = manifest_version(root)
    errors: list[str] = []

    for surface in PACKAGE_SURFACES[1:]:
        try:
            actual = read_surface(surface, root)
        except (OSError, ValueError) as error:
            errors.append(str(error))
            continue
        if actual != expected:
            errors.append(
                f"{surface.path}: {surface.label} version {actual} != {expected}"
            )

    # CI ref surfaces are pinned to the last tagged release, not the
    # in-development package version (e.g. v0.13.0-beta can stay the CI ref
    # while the package advances to 0.13.0-beta.3) — but only during pre-tag
    # development. When `--tag` (an actual release cut) or `--pre-tag` (the
    # gate before cutting tag v<package version>) is passed,
    # `require_ci_match_package` is set and every CI ref must equal the
    # package version; a tag validation must never pass while workflows
    # still point at an older ref.
    ci_expected: str | None = None
    for surface in CI_SURFACES:
        try:
            actual = read_surface(surface, root)
        except (OSError, ValueError) as error:
            errors.append(str(error))
            continue
        if require_ci_match_package:
            if actual != expected:
                errors.append(
                    f"{surface.path}: {surface.label} version {actual} != {expected} "
                    "(CI ref must equal the package version for a tagged release)"
                )
        elif ci_expected is None:
            ci_expected = actual
        elif actual != ci_expected:
            errors.append(
                f"{surface.path}: {surface.label} version {actual} != {ci_expected} (CI ref)"
            )

    return expected, errors


def current_commit(root: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def tag_commit(tag: str, root: Path = ROOT) -> str | None:
    """Return the commit *tag* peels to in *root*, or None when it is absent."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def validate_tag_available(tag: str, candidate: str, root: Path = ROOT) -> list[str]:
    """Reject an expected tag that already exists at a different commit.

    Tags are immutable, so the package version must advance. A tag that already
    points at the candidate commit is accepted: nothing conflicts and re-running
    the gate after tagging stays idempotent.
    """
    existing = tag_commit(tag, root)
    if existing is None or existing.lower() == candidate.lower():
        return []
    return [
        f"tag {tag} already exists at {existing}, not candidate {candidate}; "
        "the package version must advance to a new version"
    ]


def validate_commit(candidate: str, root: Path = ROOT) -> list[str]:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", candidate):
        return [f"candidate commit must be a 40-character SHA: {candidate}"]

    actual = current_commit(root)
    if candidate.lower() != actual.lower():
        return [f"candidate commit {candidate} != checked-out revision {actual}"]
    return []



def is_prerelease_tag(tag: str) -> bool:
    """Return True when *tag* is a SemVer prerelease (e.g. v0.13.0-beta).

    Strips a leading ``v``, ignores build metadata (``+…``), and treats any
    hyphen in the remaining core as a prerelease identifier. Stable tags such
    as ``v0.13.0`` return False.
    """
    name = tag[1:] if tag.startswith(("v", "V")) else tag
    core = name.split("+", 1)[0]
    return "-" in core


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Release tag to compare with apm.yml")
    parser.add_argument(
        "--pre-tag",
        action="store_true",
        help="Apply --tag checks against the expected tag v<package version>",
    )
    parser.add_argument("--commit", help="Candidate commit SHA")
    parser.add_argument(
        "--is-prerelease-tag",
        metavar="TAG",
        help="Exit 0 if TAG is a SemVer prerelease, 1 otherwise (no other checks)",
    )
    args = parser.parse_args(argv)

    if args.is_prerelease_tag is not None:
        return 0 if is_prerelease_tag(args.is_prerelease_tag) else 1

    version, errors = validate_versions(
        root, require_ci_match_package=bool(args.tag) or args.pre_tag
    )
    expected_tag = f"v{version}"
    if args.tag and args.tag != expected_tag:
        errors.append(f"release tag {args.tag} != {expected_tag}")
    if args.commit:
        errors.extend(validate_commit(args.commit, root))
    candidate = args.commit or current_commit(root)
    if args.pre_tag:
        errors.extend(validate_tag_available(expected_tag, candidate, root))

    print(f"candidate_revision: {candidate}")
    print(f"package_version: {version}")
    print(f"expected_tag: {expected_tag}")
    print(f"version_consistency: {'blocked' if errors else 'pass'}")
    if args.tag:
        print(f"tag_consistency: {'blocked' if errors else 'pass'}")
    if args.pre_tag:
        print(f"tag_readiness: {'blocked' if errors else 'pass'}")

    if errors:
        for error in errors:
            print(f"error: {error}")
        print("release_metadata_decision: blocked")
        return 1

    print("release_metadata_decision: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
