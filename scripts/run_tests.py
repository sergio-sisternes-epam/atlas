#!/usr/bin/env python3
"""Run every repository-owned Python test entrypoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOTS = (ROOT / "scripts", ROOT / "contributor")
TESTS = sorted(
    test
    for test_root in TEST_ROOTS
    for test in test_root.rglob("test_*.py")
)


def main() -> int:
    failures: list[str] = []

    for test in TESTS:
        relative = test.relative_to(ROOT)
        print(f"\n==> {relative}", flush=True)
        result = subprocess.run([sys.executable, str(test)], cwd=ROOT)
        if result.returncode != 0:
            failures.append(f"{relative} (exit {result.returncode})")

    if failures:
        print("\nFailed repository tests:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"\nAll {len(TESTS)} repository test entrypoints passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
