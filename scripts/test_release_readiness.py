#!/usr/bin/env python3
"""Release metadata consistency regressions."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from release_readiness import (
    ROOT,
    SURFACES,
    current_commit,
    is_prerelease_tag,
    manifest_version,
    validate_commit,
    validate_versions,
)


class ReleaseReadinessTests(unittest.TestCase):
    def test_candidate_commit_matches_checked_out_revision(self) -> None:
        self.assertEqual([], validate_commit(current_commit()))

    def test_mismatched_candidate_commit_blocks_readiness(self) -> None:
        candidate = "0" * 40
        errors = validate_commit(candidate)
        self.assertEqual(1, len(errors))
        self.assertIn("!= checked-out revision", errors[0])

    def test_malformed_candidate_commit_blocks_readiness(self) -> None:
        errors = validate_commit("main")
        self.assertEqual(
            ["candidate commit must be a 40-character SHA: main"],
            errors,
        )

    def test_repository_version_surfaces_are_consistent(self) -> None:
        version, errors = validate_versions()
        self.assertEqual(manifest_version(), version)
        self.assertEqual([], errors)


    def test_prerelease_tag_detects_beta_and_stable(self) -> None:
        self.assertTrue(is_prerelease_tag("v0.13.0-beta"))
        self.assertTrue(is_prerelease_tag("v1.2.3-rc.1"))
        self.assertTrue(is_prerelease_tag("v0.1.0-alpha.2"))
        self.assertTrue(is_prerelease_tag("0.13.0-beta"))
        self.assertFalse(is_prerelease_tag("v0.13.0"))
        self.assertFalse(is_prerelease_tag("v1.0.0"))
        # Build metadata alone is not a prerelease
        self.assertFalse(is_prerelease_tag("v1.0.0+build.1"))
        self.assertTrue(is_prerelease_tag("v1.0.0-beta+build.1"))

    def test_mismatched_surface_blocks_readiness(self) -> None:
        expected = manifest_version()
        mismatched = "99.99.99"
        temp = Path(tempfile.mkdtemp(prefix="atlas-release-readiness-"))
        try:
            for surface in SURFACES:
                source = ROOT / surface.path
                target = temp / surface.path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

            cli = temp / "scripts/atlas_cli/__init__.py"
            cli.write_text(
                cli.read_text(encoding="utf-8").replace(expected, mismatched),
                encoding="utf-8",
            )

            version, errors = validate_versions(temp)
            self.assertEqual(expected, version)
            self.assertEqual(1, len(errors))
            self.assertIn(
                f"Python CLI version {mismatched} != {expected}",
                errors[0],
            )
        finally:
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
