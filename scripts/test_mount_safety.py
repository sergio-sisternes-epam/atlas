#!/usr/bin/env python3
"""Focused mount safety regressions. Run: python3 scripts/test_mount_safety.py"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from atlas_cli.commands.mount import _in_gitmodules

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


def json_payload(result: subprocess.CompletedProcess[str]) -> tuple[dict, str]:
    try:
        return json.loads(result.stdout), ""
    except json.JSONDecodeError as error:
        detail = (
            f"invalid JSON ({error}); stdout={result.stdout!r}; "
            f"stderr={result.stderr!r}"
        )
        return {}, detail


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
        payload, parse_error = json_payload(result)
        check(
            "external-target-rejected",
            result.returncode == 2
            and "inside the active git repository" in payload.get("error", "")
            and not outside.exists(),
            parse_error or f"exit={result.returncode} payload={payload}",
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
        payload, parse_error = json_payload(result)
        check(
            "dirty-existing-checkout-rejected-before-registration",
            result.returncode == 2
            and "dirty worktree" in payload.get("error", "")
            and not (parent / ".gitmodules").exists(),
            parse_error or f"exit={result.returncode} payload={payload}",
        )

        (parent / ".gitmodules").write_text(
            '[submodule "store-extra"]\n'
            "\tpath = .atlas/github.com/example/store-extra\n"
            "\turl = https://github.com/example/store-extra.git\n",
            encoding="utf-8",
        )
        wanted = parent / ".atlas/github.com/example/store"
        listed = parent / ".atlas/github.com/example/store-extra"
        check(
            "gitmodules-path-match-is-exact",
            not _in_gitmodules(parent, wanted)
            and _in_gitmodules(parent, listed),
            "a submodule path must not match a longer path by substring",
        )

        caller = tmp / "caller"
        caller.mkdir()
        relative_existing = parent / "relative-existing"
        relative_existing.mkdir()
        git(["init", "-q"], relative_existing)
        (relative_existing / "dirty.md").write_text("uncommitted\n", encoding="utf-8")
        result = run(
            [
                "mount",
                "github.com/example/store",
                "--target",
                "relative-existing",
                "--cwd",
                str(parent),
                "--json",
            ],
            caller,
        )
        payload, parse_error = json_payload(result)
        check(
            "relative-target-resolves-from-selected-repository",
            result.returncode == 2
            and "dirty worktree" in payload.get("error", "")
            and str(relative_existing) in payload.get("error", ""),
            parse_error or f"exit={result.returncode} payload={payload}",
        )

        (parent / ".gitmodules").unlink()
        unrelated = parent / "unrelated"
        unrelated.mkdir()
        git(["init", "-q"], unrelated)
        git(
            ["remote", "add", "origin", "https://github.com/example/other.git"],
            unrelated,
        )
        result = run(
            [
                "mount",
                "github.com/example/store",
                "--target",
                "unrelated",
                "--cwd",
                str(parent),
                "--json",
            ],
            parent,
        )
        payload, parse_error = json_payload(result)
        check(
            "unrelated-existing-checkout-rejected",
            result.returncode == 2
            and "github.com/example/other" in payload.get("error", "")
            and "expected github.com/example/store" in payload.get("error", "")
            and not (parent / ".gitmodules").exists(),
            parse_error or f"exit={result.returncode} payload={payload}",
        )

        matching = parent / "matching"
        matching.mkdir()
        git(["init", "-q"], matching)
        git(["config", "user.name", "Atlas Test"], matching)
        git(["config", "user.email", "atlas@example.invalid"], matching)
        (matching / "SCHEMA.json").write_text("{}\n", encoding="utf-8")
        git(["add", "SCHEMA.json"], matching)
        git(["commit", "-q", "-m", "Initial store"], matching)
        git(
            ["remote", "add", "origin", "git@github.com:example/store.git"],
            matching,
        )
        result = run(
            [
                "mount",
                "https://github.com/example/store.git",
                "--target",
                "matching",
                "--cwd",
                str(parent),
                "--json",
            ],
            parent,
        )
        payload, parse_error = json_payload(result)
        check(
            "matching-existing-checkout-registered",
            result.returncode == 0
            and payload.get("id") == "github.com/example/store"
            and _in_gitmodules(parent, matching),
            parse_error
            or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
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
