"""Git helpers for mount/resolve. Git is the overlay."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def has_git() -> bool:
    return shutil.which("git") is not None


def run_git(args: list[str], cwd: Path | None = None, env: dict | None = None) -> tuple[int, str, str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    p = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def git_root(start: Path) -> Path | None:
    code, out, _ = run_git(["rev-parse", "--show-toplevel"], cwd=start)
    if code == 0 and out:
        return Path(out)
    return None


def is_dirty(repo: Path) -> bool:
    code, out, _ = run_git(["status", "--porcelain"], cwd=repo)
    return code == 0 and bool(out)


def current_branch(repo: Path) -> str:
    code, out, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    return out if code == 0 else ""


def _auth_prefix(token: str | None) -> list[str]:
    if not token:
        return []
    return ["-c", f"http.extraHeader=Authorization: Bearer {token}"]


def clone(
    url: str,
    dest: Path,
    ref: str | None,
    extra_env: dict | None = None,
    token: str | None = None,
) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = [*_auth_prefix(token), "clone"]
    if ref:
        args.extend(["--branch", ref])
    args.extend([url, str(dest)])
    code, _out, err = run_git(args, env=extra_env)
    return code, err


def submodule_add(
    parent: Path,
    url: str,
    dest: Path,
    ref: str | None,
    token: str | None = None,
) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent)
    args = [*_auth_prefix(token), "submodule", "add"]
    if ref:
        args.extend(["-b", ref])
    args.extend([url, rel])
    code, _out, err = run_git(args, cwd=parent)
    return code, err


def submodule_init(parent: Path, dest: Path) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent)
    code, _out, err = run_git(["submodule", "update", "--init", "--", rel], cwd=parent)
    return code, err
