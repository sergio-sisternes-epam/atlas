#!/usr/bin/env python3
"""Focused validation warning regressions. Run: python3 scripts/test_validation_warnings.py"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-validation-warnings-"))
    try:
        store = tmp / "store"
        init = run(["init", "--root", str(store), "--json"])
        if init.returncode != 0:
            print(f"[FAIL] init: exit={init.returncode} stderr={init.stderr!r}")
            return 1

        notes = store / "notes"
        notes.mkdir()
        (notes / "index.md").write_text("# Notes\n\n- dependency\n", encoding="utf-8")
        (notes / "dependency.md").write_text(
            "---\n"
            "type: document\n"
            "title: External dependency\n"
            "created: 2026-09-03\n"
            "---\n\n"
            "## Content\n\n"
            "This document depends on "
            "atlas://github.com/example/external-store/topic.md "
            "without requiring that Atlas to be mounted locally.\n",
            encoding="utf-8",
        )

        failures: list[str] = []
        for command in ("validate", "compile"):
            result = run([command, "--root", str(store), "--json"])
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as error:
                failures.append(
                    f"{command}: invalid JSON ({error}); stdout={result.stdout!r}; "
                    f"stderr={result.stderr!r}"
                )
                continue

            warning_ids = [issue.get("id") for issue in payload.get("warnings", [])]
            passed = (
                result.returncode == 0
                and payload.get("critical") == []
                and warning_ids == ["atlas_uri_unmounted"]
            )
            print(f"[{'PASS' if passed else 'FAIL'}] {command}")
            if not passed:
                failures.append(
                    f"{command}: exit={result.returncode} "
                    f"warnings={warning_ids} critical={payload.get('critical')} "
                    f"stderr={result.stderr!r}"
                )

        if failures:
            print("\n" + "\n".join(failures))
            return 1
        print("\nAll validation warning regressions passed")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
