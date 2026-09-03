#!/usr/bin/env python3
"""Focused mount safety regressions. Run: python3 scripts/test_mount_safety.py"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mount-safety-"))
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str) -> None:
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    try:
        parent = tmp / "parent"
        parent.mkdir()
        git(["init", "-q"], parent)

        outside = tmp / "outside"
        result = run(
            [
                "mount",
                "github.com/example/store",
                "--target",
                str(outside),
                "--cwd",
                str(parent),
                "--json",
            ],
            parent,
        )
        payload = json.loads(result.stdout)
        check(
            "external-target-rejected",
            result.returncode == 2
            and "inside the active git repository" in payload.get("error", "")
            and not outside.exists(),
            f"exit={result.returncode} payload={payload}",
        )

        existing = parent / "existing"
        existing.mkdir()
        git(["init", "-q"], existing)
        (existing / "dirty.md").write_text("uncommitted\n", encoding="utf-8")
        result = run(
            [
                "mount",
                "github.com/example/store",
                "--target",
                str(existing),
                "--cwd",
                str(parent),
                "--json",
            ],
            parent,
        )
        payload = json.loads(result.stdout)
        check(
            "dirty-existing-checkout-rejected-before-registration",
            result.returncode == 2
            and "dirty worktree" in payload.get("error", "")
            and not (parent / ".gitmodules").exists(),
            f"exit={result.returncode} payload={payload}",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\n" + "\n".join(failures))
        return 1
    print("\nAll mount safety regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
