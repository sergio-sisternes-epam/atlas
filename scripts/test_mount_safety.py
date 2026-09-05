#!/usr/bin/env python3
"""Focused mount safety regressions. Run: python3 scripts/test_mount_safety.py"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from atlas_cli.commands.mount import _in_gitmodules
from atlas_cli.core.gitops import (
    capture_submodule_state,
    rollback_submodule_state,
)

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


def run(
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
    )


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def git_output(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def init_parent(path: Path) -> None:
    path.mkdir()
    git(["init", "-q", "--initial-branch=main"], path)
    git(["config", "user.name", "Atlas Test"], path)
    git(["config", "user.email", "atlas@example.invalid"], path)
    (path / ".keep").write_text("", encoding="utf-8")
    git(["add", ".keep"], path)
    git(["commit", "-q", "-m", "Parent"], path)


def local_remote_env(remote: Path, public_url: str) -> dict[str, str]:
    return {
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.file://{remote}.insteadOf",
        "GIT_CONFIG_VALUE_0": public_url,
    }


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
        init_parent(parent)

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

        mesh = parent / "atlas-mesh.json"
        mesh.unlink(missing_ok=True)
        result = run(
            [
                "mount",
                "github.com/example/store",
                "--target",
                "matching",
                "--cwd",
                str(parent),
                "--json",
            ],
            parent,
        )
        payload, parse_error = json_payload(result)
        mesh_payload = json.loads(mesh.read_text(encoding="utf-8")) if mesh.exists() else {}
        check(
            "registered-checkout-repairs-missing-mesh",
            result.returncode == 0
            and payload.get("status") == "noop"
            and mesh_payload.get("stores", [{}])[0].get("id")
            == "github.com/example/store",
            parse_error
            or f"exit={result.returncode} payload={payload} mesh={mesh_payload}",
        )

        empty_remote = tmp / "empty.git"
        git(["init", "-q", "--bare", "--initial-branch=main", str(empty_remote)], tmp)
        empty_parent = tmp / "empty-parent"
        init_parent(empty_parent)
        empty_url = "https://github.com/example/empty.git"
        empty_env = local_remote_env(empty_remote, empty_url)
        empty_target = empty_parent / "store"
        result = run(
            [
                "mount",
                empty_url,
                "--ref",
                "main",
                "--target",
                "store",
                "--cwd",
                str(empty_parent),
                "--json",
            ],
            empty_parent,
            empty_env,
        )
        payload, parse_error = json_payload(result)
        empty_mesh = empty_parent / "atlas-mesh.json"
        empty_mesh_payload = (
            json.loads(empty_mesh.read_text(encoding="utf-8"))
            if empty_mesh.exists()
            else {}
        )
        check(
            "empty-remote-mount-bootstraps-registered-submodule",
            result.returncode == 0
            and payload.get("ref") == "main"
            and _in_gitmodules(empty_parent, empty_target)
            and git_output(["ls-files", "-s", "--", "store"], empty_parent).startswith(
                "160000"
            )
            and git_output(["rev-list", "--count", "HEAD"], empty_target) == "1"
            and git_output(["ls-tree", "--name-only", "HEAD"], empty_target) == ""
            and empty_mesh_payload.get("stores", [{}])[0].get("id")
            == "github.com/example/empty",
            parse_error
            or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        second_parent = tmp / "second-empty-parent"
        init_parent(second_parent)
        second_target = second_parent / "store"
        result = run(
            [
                "mount",
                empty_url,
                "--ref",
                "main",
                "--target",
                "store",
                "--cwd",
                str(second_parent),
                "--json",
            ],
            second_parent,
            empty_env,
        )
        payload, parse_error = json_payload(result)
        check(
            "empty-remote-bootstrap-is-deterministic",
            result.returncode == 0
            and git_output(["rev-parse", "HEAD"], second_target)
            == git_output(["rev-parse", "HEAD"], empty_target),
            parse_error
            or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        result = run(
            [
                "mount",
                empty_url,
                "--ref",
                "main",
                "--target",
                "store",
                "--cwd",
                str(empty_parent),
                "--json",
            ],
            empty_parent,
            empty_env,
        )
        payload, parse_error = json_payload(result)
        check(
            "empty-remote-remount-is-noop",
            result.returncode == 0
            and payload.get("status") == "noop"
            and git_output(["rev-list", "--count", "HEAD"], empty_target) == "1",
            parse_error
            or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        result = run(
            ["init", "--root", str(empty_target), "--json"],
            empty_parent,
        )
        payload, parse_error = json_payload(result)
        check(
            "empty-remote-mounted-checkout-can-be-initialized",
            result.returncode == 0
            and payload.get("ok") is True
            and (empty_target / "SCHEMA.json").is_file(),
            parse_error
            or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        other_remote = tmp / "other.git"
        git(["init", "-q", "--bare", "--initial-branch=other", str(other_remote)], tmp)
        seed = tmp / "seed"
        git(["clone", "-q", str(other_remote), str(seed)], tmp)
        git(["config", "user.name", "Atlas Test"], seed)
        git(["config", "user.email", "atlas@example.invalid"], seed)
        (seed / "data.md").write_text("non-empty\n", encoding="utf-8")
        git(["add", "data.md"], seed)
        git(["commit", "-q", "-m", "Seed"], seed)
        git(["push", "-q", "origin", "other"], seed)

        rollback_parent = tmp / "rollback-parent"
        init_parent(rollback_parent)
        original_gitmodules = (
            '[submodule "kept"]\n'
            "\tpath = kept\n"
            "\turl = https://github.com/example/kept.git\n"
        )
        (rollback_parent / ".gitmodules").write_text(
            original_gitmodules,
            encoding="utf-8",
        )
        git(["add", ".gitmodules"], rollback_parent)
        git(["commit", "-q", "-m", "Keep submodule config"], rollback_parent)
        other_url = "https://github.com/example/other.git"
        result = run(
            [
                "mount",
                other_url,
                "--ref",
                "main",
                "--target",
                "failed-store",
                "--cwd",
                str(rollback_parent),
                "--json",
            ],
            rollback_parent,
            local_remote_env(other_remote, other_url),
        )
        payload, parse_error = json_payload(result)
        check(
            "failed-mount-rolls-back-partial-submodule",
            result.returncode == 2
            and not (rollback_parent / "failed-store").exists()
            and not (rollback_parent / ".git/modules/failed-store").exists()
            and (rollback_parent / ".gitmodules").read_text(encoding="utf-8")
            == original_gitmodules
            and git_output(["status", "--porcelain"], rollback_parent) == ""
            and not (rollback_parent / "atlas-mesh.json").exists(),
            parse_error
            or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        absorb_parent = tmp / "absorb-parent"
        init_parent(absorb_parent)
        standalone = absorb_parent / "standalone"
        git(["clone", "-q", str(other_remote), str(standalone)], absorb_parent)
        before_status = git_output(["status", "--porcelain"], absorb_parent)
        absorb_snapshot = capture_submodule_state(absorb_parent, standalone)
        (absorb_parent / ".gitmodules").write_text(
            '[submodule "standalone"]\n'
            "\tpath = standalone\n"
            f"\turl = {other_remote}\n",
            encoding="utf-8",
        )
        git(["add", ".gitmodules", "standalone"], absorb_parent)
        git(["submodule", "absorbgitdirs", "--", "standalone"], absorb_parent)
        rollback_errors = rollback_submodule_state(absorb_snapshot)
        child_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=standalone,
            text=True,
            capture_output=True,
        )
        check(
            "rollback-restores-absorbed-standalone-checkout",
            not rollback_errors
            and (standalone / ".git").is_dir()
            and child_status.returncode == 0
            and git_output(["status", "--porcelain"], absorb_parent)
            == before_status,
            f"errors={rollback_errors} child_stderr={child_status.stderr!r}",
        )

        (seed / "second.md").write_text("second\n", encoding="utf-8")
        git(["add", "second.md"], seed)
        git(["commit", "-q", "-m", "Second"], seed)
        git(["push", "-q", "origin", "other"], seed)
        first_commit = git_output(
            ["rev-list", "--max-parents=0", "HEAD"],
            seed,
        )

        deinit_parent = tmp / "deinit-parent"
        init_parent(deinit_parent)
        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(other_remote),
                "module",
            ],
            cwd=deinit_parent,
            check=True,
            capture_output=True,
        )
        git(["commit", "-q", "-m", "Add module"], deinit_parent)
        git(["submodule", "deinit", "-f", "--", "module"], deinit_parent)
        deinit_target = deinit_parent / "module"
        deinit_snapshot = capture_submodule_state(deinit_parent, deinit_target)
        module_gitdir = deinit_parent / ".git/modules/module"
        original_module_head = git_output(
            ["--git-dir", str(module_gitdir), "rev-parse", "HEAD"],
            deinit_parent,
        )
        git(
            [
                "--git-dir",
                str(module_gitdir),
                "update-ref",
                "--no-deref",
                "HEAD",
                first_commit,
            ],
            deinit_parent,
        )
        rollback_errors = rollback_submodule_state(deinit_snapshot)
        check(
            "rollback-restores-deinitialized-submodule-head",
            not rollback_errors
            and git_output(
                ["--git-dir", str(module_gitdir), "rev-parse", "HEAD"],
                deinit_parent,
            )
            == original_module_head,
            f"errors={rollback_errors}",
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
