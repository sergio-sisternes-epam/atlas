#!/usr/bin/env python3
"""Release metadata consistency regressions."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from release_readiness import ROOT, SURFACES, manifest_version, validate_versions


class ReleaseReadinessTests(unittest.TestCase):
    def test_repository_version_surfaces_are_consistent(self) -> None:
        version, errors = validate_versions()
        self.assertEqual(manifest_version(), version)
        self.assertEqual([], errors)

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
