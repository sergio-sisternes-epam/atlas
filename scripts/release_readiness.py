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


SURFACES = (
    VersionSurface("manifest", "apm.yml", rf"^version:\s*({SEMVER})\s*$"),
    VersionSurface("skill", "SKILL.md", rf"^version:\s*({SEMVER})\s*$"),
    VersionSurface(
        "Python CLI",
        "scripts/atlas_cli/__init__.py",
        rf'^__version__\s*=\s*"({SEMVER})"\s*$',
    ),
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


def read_surface(surface: VersionSurface, root: Path = ROOT) -> str:
    content = (root / surface.path).read_text(encoding="utf-8")
    matches = re.findall(surface.pattern, content, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(
            f"{surface.path}: expected one {surface.label} version, found {len(matches)}"
        )
    return matches[0]


def manifest_version(root: Path = ROOT) -> str:
    return read_surface(SURFACES[0], root)


def validate_versions(root: Path = ROOT) -> tuple[str, list[str]]:
    expected = manifest_version(root)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Release tag to compare with apm.yml")
    parser.add_argument("--commit", help="Candidate commit SHA")
    args = parser.parse_args()

    version, errors = validate_versions()
    expected_tag = f"v{version}"
    if args.tag and args.tag != expected_tag:
        errors.append(f"release tag {args.tag} != {expected_tag}")

    print(f"candidate_revision: {args.commit or current_commit()}")
    print(f"package_version: {version}")
    print(f"expected_tag: {expected_tag}")
    print(f"version_consistency: {'blocked' if errors else 'pass'}")
    if args.tag:
        print(f"tag_consistency: {'blocked' if errors else 'pass'}")

    if errors:
        for error in errors:
            print(f"error: {error}")
        print("release_metadata_decision: blocked")
        return 1

    print("release_metadata_decision: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
