#!/usr/bin/env python3
"""TEST-ONLY Atlas CLI entry. Never use it outside the test suite.

Reads ``ATLAS_TEST_PLATFORM`` (for example ``darwin-arm64``), installs it as
the platform provider through
``driver_overlay.set_platform_provider_for_tests``, lets the fake nanograph's
own ``FAKE_NANOGRAPH_*`` controls through the external driver environment
allow-list, and then runs the normal CLI. The production entry ``scripts/atlas.py`` does not import this module, and
no code under ``scripts/atlas_cli/`` reads ``ATLAS_TEST_PLATFORM``, so the
platform gate in production always reflects the real platform.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas_cli.cli import main  # noqa: E402
from atlas_cli.core import driver_overlay  # noqa: E402
from atlas_cli.core.drivers import subprocess_env  # noqa: E402

TEST_PLATFORM_ENV = "ATLAS_TEST_PLATFORM"


def install_test_platform() -> None:
    raw = os.environ.get(TEST_PLATFORM_ENV, "").strip()
    if not raw:
        return
    if "-" not in raw:
        raise SystemExit(f"{TEST_PLATFORM_ENV} must look like <sys.platform>-<machine>, got {raw!r}")
    plat, machine = raw.split("-", 1)
    driver_overlay.set_platform_provider_for_tests(lambda: (plat, machine))


if __name__ == "__main__":
    install_test_platform()
    subprocess_env.set_test_passthrough_prefixes(("FAKE_NANOGRAPH_",))
    main()
