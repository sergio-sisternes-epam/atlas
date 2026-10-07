#!/usr/bin/env python3
"""Release metadata consistency regressions."""

from __future__ import annotations

import contextlib
import io
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
    main,
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
        # Development (require_ci_match_package=False, the no-flag default):
        # CI ref surfaces are allowed to lag the package version as long as
        # they all agree with *each other*. This exercises the real surfaces;
        # the synthetic lag case is covered below.
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

    def _copy_surfaces(self, prefix: str) -> Path:
        temp = Path(tempfile.mkdtemp(prefix=prefix))
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        for surface in SURFACES:
            target = temp / surface.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / surface.path, target)
        return temp

    def _set_ci_refs(self, root: Path, version: str) -> None:
        for surface in CI_SURFACES:
            path = root / surface.path
            content = path.read_text(encoding="utf-8")
            for actual in re.findall(surface.pattern, content, re.MULTILINE):
                content = content.replace(f"v{actual}", f"v{version}")
            path.write_text(content, encoding="utf-8")

    def _run_main(self, argv: list[str], root: Path) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(argv, root)
        return code, output.getvalue()

    def test_pre_tag_mode_passes_when_ci_refs_equal_package_version(self) -> None:
        temp = self._copy_surfaces("atlas-release-readiness-pretag-pass-")
        package_version = manifest_version(temp)
        self._set_ci_refs(temp, package_version)

        code, output = self._run_main(["--pre-tag"], temp)
        self.assertEqual(0, code, output)
        self.assertIn(f"expected_tag: v{package_version}", output)
        self.assertIn("tag_readiness: pass", output)
        self.assertIn("release_metadata_decision: pass", output)

    def test_pre_tag_mode_blocks_when_ci_ref_lags(self) -> None:
        temp = self._copy_surfaces("atlas-release-readiness-pretag-block-")
        package_version = manifest_version(temp)
        self._set_ci_refs(temp, package_version)
        lagging = CI_SURFACES[0]
        path = temp / lagging.path
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                f"v{package_version}", "v0.1.0"
            ),
            encoding="utf-8",
        )

        code, output = self._run_main(["--pre-tag"], temp)
        self.assertEqual(1, code, output)
        self.assertIn("tag_readiness: blocked", output)
        self.assertIn("release_metadata_decision: blocked", output)
        self.assertIn(
            f"error: {lagging.path}: {lagging.label} version 0.1.0 != {package_version} "
            "(CI ref must equal the package version for a tagged release)",
            output,
        )

    def test_no_flag_mode_allows_consistent_ci_lag(self) -> None:
        temp = self._copy_surfaces("atlas-release-readiness-lag-")
        self._set_ci_refs(temp, "0.1.0")

        code, output = self._run_main([], temp)
        self.assertEqual(0, code, output)
        self.assertNotIn("tag_readiness", output)
        self.assertIn("release_metadata_decision: pass", output)


if __name__ == "__main__":
    unittest.main()
