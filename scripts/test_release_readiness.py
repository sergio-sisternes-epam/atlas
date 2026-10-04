#!/usr/bin/env python3
"""Release metadata consistency regressions."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from release_readiness import (
    CI_SURFACES,
    ROOT,
    SURFACES,
    current_commit,
    is_prerelease_tag,
    manifest_version,
    read_surface,
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

    def test_pretag_allows_package_ci_lag_when_ci_refs_agree(self) -> None:
        # Pre-tag (require_ci_match_package=False, the `compile` default): CI
        # ref surfaces are allowed to lag the package version as long as they
        # all agree with *each other*. The checked-out tree already carries
        # this exact lag (package at a .N beta while CI refs still point at
        # the last tagged beta), so this exercises the real surfaces rather
        # than a synthetic fixture.
        version, errors = validate_versions(ROOT, require_ci_match_package=False)
        self.assertEqual(manifest_version(), version)
        self.assertEqual([], errors)
        ci_versions = {read_surface(surface) for surface in CI_SURFACES}
        self.assertEqual(1, len(ci_versions), "CI ref surfaces must agree with each other")

    def test_tag_rejects_lagging_ci_refs(self) -> None:
        # `--tag` (require_ci_match_package=True, an actual release cut) must
        # not pass while CI refs still point at an older tagged ref than the
        # package version — this is the exact shape of the checked-out tree.
        version, errors = validate_versions(ROOT, require_ci_match_package=True)
        ci_versions = {read_surface(surface) for surface in CI_SURFACES}
        if ci_versions == {version}:
            self.skipTest("CI refs already match the package version; nothing to reject")
        self.assertTrue(errors, "require_ci_match_package=True must reject lagging CI refs")
        for surface in CI_SURFACES:
            actual = read_surface(surface)
            if actual != version:
                self.assertTrue(
                    any(surface.path in error and "CI ref must equal" in error for error in errors),
                    f"expected a CI-ref-must-equal-package error for {surface.path}; got {errors}",
                )

    def test_tag_rejects_lagging_ci_refs_synthetic(self) -> None:
        # Deterministic companion to the above: build a temp tree where the
        # package version is newer than every CI ref (which still agree with
        # each other) and assert `--tag` semantics (require_ci_match_package)
        # reject it while pre-tag semantics accept it.
        temp = Path(tempfile.mkdtemp(prefix="atlas-release-readiness-tag-"))
        try:
            for surface in SURFACES:
                source = ROOT / surface.path
                target = temp / surface.path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

            package_version = manifest_version(temp)
            lagging_ci_version = "0.1.0"
            self.assertNotEqual(package_version, lagging_ci_version)
            for surface in CI_SURFACES:
                path = temp / surface.path
                content = path.read_text(encoding="utf-8")
                for actual in re.findall(surface.pattern, content, re.MULTILINE):
                    content = content.replace(f"v{actual}", f"v{lagging_ci_version}")
                path.write_text(content, encoding="utf-8")

            # Pre-tag: CI refs lag the package version but agree with each
            # other, so this must still pass.
            pretag_version, pretag_errors = validate_versions(
                temp, require_ci_match_package=False
            )
            self.assertEqual(package_version, pretag_version)
            self.assertEqual([], pretag_errors)

            # `--tag`: the same lagging CI refs must now be rejected.
            tag_version, tag_errors = validate_versions(temp, require_ci_match_package=True)
            self.assertEqual(package_version, tag_version)
            self.assertTrue(tag_errors)
            self.assertTrue(
                all("CI ref must equal the package version" in e for e in tag_errors)
            )
        finally:
            shutil.rmtree(temp, ignore_errors=True)



if __name__ == "__main__":
    unittest.main()
