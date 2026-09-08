#!/usr/bin/env python3
"""Validate OKF release metadata against one package version."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_NUMBER = r"(?:0|[1-9][0-9]*)"
CORE_VERSION = rf"{VERSION_NUMBER}\.{VERSION_NUMBER}\.{VERSION_NUMBER}"
NON_NUMERIC_IDENTIFIER = r"[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*"
PRERELEASE_IDENTIFIER = (
    rf"(?:0|[1-9][0-9]*|{NON_NUMERIC_IDENTIFIER})"
)
SEMVER = (
    rf"(?:{CORE_VERSION})"
    rf"(?:-{PRERELEASE_IDENTIFIER}(?:\.{PRERELEASE_IDENTIFIER})*)?"
)


@dataclass(frozen=True)
class VersionSurface:
    label: str
    path: str
    pattern: str


SURFACES = (
    VersionSurface("manifest", "apm.yml", rf"^version:\s*({SEMVER})\s*$"),
    VersionSurface("skill", "SKILL.md", rf"^version:\s*({SEMVER})\s*$"),
    VersionSurface(
        "install command",
        "README.md",
        rf"^apm install sergio-sisternes-epam/okf#v({SEMVER})\s*$",
    ),
    VersionSurface(
        "dependency example",
        "README.md",
        rf"^\s*-\s+sergio-sisternes-epam/okf#v({SEMVER})\s*$",
    ),
)
CHANGELOG_PATTERN = (
    rf"^## \[({SEMVER})\] - [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}\s*$"
)


def read_surface(surface: VersionSurface, root: Path = ROOT) -> str:
    content = (root / surface.path).read_text(encoding="utf-8")
    matches = re.findall(surface.pattern, content, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(
            f"{surface.path}: expected one {surface.label} version, "
            f"found {len(matches)}"
        )
    return matches[0]


def manifest_version(root: Path = ROOT) -> str:
    return read_surface(SURFACES[0], root)


def validate_versions(root: Path = ROOT) -> tuple[str | None, list[str]]:
    try:
        expected = manifest_version(root)
    except (OSError, ValueError) as error:
        return None, [str(error)]

    errors: list[str] = []

    for surface in SURFACES[1:]:
        try:
            actual = read_surface(surface, root)
        except (OSError, ValueError) as error:
            errors.append(str(error))
            continue
        if actual != expected:
            errors.append(
                f"{surface.path}: {surface.label} version {actual} != {expected}"
            )

    try:
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        changelog_versions = re.findall(CHANGELOG_PATTERN, changelog, re.MULTILINE)
    except OSError as error:
        errors.append(str(error))
    else:
        count = changelog_versions.count(expected)
        if count != 1:
            errors.append(
                "CHANGELOG.md: expected one current package version "
                f"{expected}, found {count}"
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


def validate_commit(candidate: str, root: Path = ROOT) -> list[str]:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", candidate):
        return [f"candidate commit must be a 40-character SHA: {candidate}"]

    actual = current_commit(root)
    if candidate.lower() != actual.lower():
        return [f"candidate commit {candidate} != checked-out revision {actual}"]
    return []


def is_prerelease(version: str) -> bool:
    return "-" in version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Pushed release tag to compare with apm.yml")
    parser.add_argument("--commit", help="Candidate commit SHA")
    args = parser.parse_args()

    version, version_errors = validate_versions()
    if version is None:
        print("candidate_revision: unknown")
        print("package_version: unknown")
        print("expected_tag: unknown")
        print("is_prerelease: unknown")
        print("version_consistency: blocked")
        for error in version_errors:
            print(f"error: {error}")
        print("release_metadata_decision: blocked")
        return 1

    expected_tag = f"v{version}"
    tag_errors: list[str] = []
    if args.tag and args.tag != expected_tag:
        tag_errors.append(f"release tag {args.tag} != {expected_tag}")

    commit_errors: list[str] = []
    if args.commit:
        commit_errors.extend(validate_commit(args.commit))

    errors = version_errors + tag_errors + commit_errors

    prerelease = is_prerelease(version)
    print(f"candidate_revision: {args.commit or current_commit()}")
    print(f"package_version: {version}")
    print(f"expected_tag: {expected_tag}")
    print(f"is_prerelease: {str(prerelease).lower()}")
    print(
        f"version_consistency: {'blocked' if version_errors else 'pass'}"
    )
    if args.tag:
        print(f"tag_consistency: {'blocked' if tag_errors else 'pass'}")
    if args.commit:
        print(
            f"commit_consistency: {'blocked' if commit_errors else 'pass'}"
        )

    if errors:
        for error in errors:
            print(f"error: {error}")
        print("release_metadata_decision: blocked")
        return 1

    print("release_metadata_decision: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
